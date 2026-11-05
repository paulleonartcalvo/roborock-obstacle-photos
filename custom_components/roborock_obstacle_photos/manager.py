"""Fetch and store obstacle photos for one Roborock vacuum."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from pathlib import Path
from typing import Any

from roborock.exceptions import RoborockException

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EVENT_NEW_PHOTO,
    PET_TYPES,
    ROBOROCK_DOMAIN,
    STORAGE_VERSION,
    signal_updated,
)
from .map_obstacles import MapObstacle, parse_obstacles_with_photo

_LOGGER = logging.getLogger(__name__)


def async_get_managers(hass: HomeAssistant) -> list[ObstaclePhotoManager]:
    """Return the managers of the loaded config entry."""
    return [
        manager
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        for manager in entry.runtime_data
    ]


def async_get_manager(hass: HomeAssistant, duid: str) -> ObstaclePhotoManager | None:
    """Return the manager for a vacuum."""
    return next(
        (manager for manager in async_get_managers(hass) if manager.duid == duid),
        None,
    )


class ObstaclePhotoManager:
    """Watches a vacuum's map and saves every new obstacle photo to /media."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, coordinator: Any
    ) -> None:
        """Initialize the manager for a core Roborock V1 coordinator."""
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.duid: str = coordinator.duid
        self.device_name: str = coordinator.device_info.get("name") or self.duid
        self.media_root = Path(
            hass.config.media_dirs.get("local") or hass.config.path("media")
        )
        self.photo_dir = self.media_root / DOMAIN / coordinator.duid_slug
        self.current_obstacles: list[MapObstacle] = []
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{self.duid}"
        )
        self._photos: dict[str, dict[str, Any]] = {}
        self._latest: str | None = None
        self._latest_pet: str | None = None
        self._lock = asyncio.Lock()
        self._unsub: Callable[[], None] | None = None

    @property
    def device_entry(self) -> dr.DeviceEntry | None:
        """The vacuum's device as registered by the core Roborock integration."""
        registry = dr.async_get(self.hass)
        return next(
            (
                device
                for device in dr.async_entries_for_config_entry(
                    registry, self.coordinator.config_entry.entry_id
                )
                if (ROBOROCK_DOMAIN, self.duid) in device.identifiers
            ),
            None,
        )

    @property
    def supported(self) -> bool:
        """Whether the vacuum exposes obstacle photos."""
        return self.coordinator.properties_api.obstacle_photos is not None

    @property
    def photo_count(self) -> int:
        """Number of photos saved so far."""
        return len(self._photos)

    def photos(self, *, pet: bool | None = None) -> list[dict[str, Any]]:
        """Saved photo records, newest first, optionally only (non-)pets."""
        records = [
            record
            for record in self._photos.values()
            if pet is None or record["is_pet"] == pet
        ]
        return sorted(records, key=lambda record: record["captured_at"], reverse=True)

    def photo(self, photo_id: str) -> dict[str, Any] | None:
        """Return a saved photo record by id."""
        return self._photos.get(photo_id)

    def latest(self, *, pet: bool = False) -> dict[str, Any] | None:
        """Return the record of the newest saved photo."""
        photo_id = self._latest_pet if pet else self._latest
        return self._photos.get(photo_id) if photo_id else None

    async def async_start(self) -> None:
        """Load saved state and start watching map updates."""
        if data := await self._store.async_load():
            self._photos = data.get("photos", {})
            self._latest = data.get("latest")
            self._latest_pet = data.get("latest_pet")
        self._unsub = self.coordinator.properties_api.home.add_update_listener(
            self._handle_home_update
        )

    @callback
    def async_stop(self) -> None:
        """Stop watching map updates."""
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _handle_home_update(self) -> None:
        self.entry.async_create_background_task(
            self.hass, self.async_process(), name=f"{DOMAIN}_process_{self.duid}"
        )

    async def async_refresh(self) -> None:
        """Ask the core integration for a fresh map, then process it."""
        await self.coordinator.update_map()
        await self.async_process()

    async def async_process(self) -> None:
        """Read the current map and fetch any photos not saved yet."""
        async with self._lock:
            raw = self.coordinator.properties_api.map_content.raw_api_response
            if not raw:
                return
            try:
                self.current_obstacles = await self.hass.async_add_executor_job(
                    parse_obstacles_with_photo, raw
                )
            except (ValueError, IndexError) as err:
                _LOGGER.debug("Could not read obstacles from map: %s", err)
                return

            photos_trait = self.coordinator.properties_api.obstacle_photos
            new_records = []
            if photos_trait is not None:
                for obstacle in self.current_obstacles:
                    if obstacle.photo_id in self._photos:
                        continue
                    try:
                        photo = await photos_trait.get_photo(obstacle.photo_id)
                    except RoborockException as err:
                        _LOGGER.debug(
                            "Fetching photo %s failed, will retry: %s",
                            obstacle.photo_id,
                            err,
                        )
                        continue
                    record = await self.hass.async_add_executor_job(
                        self._save_photo, obstacle, photo.image_content
                    )
                    self._photos[obstacle.photo_id] = record
                    self._latest = obstacle.photo_id
                    if record["is_pet"]:
                        self._latest_pet = obstacle.photo_id
                    new_records.append(record)

            if new_records:
                await self._store.async_save(
                    {
                        "photos": self._photos,
                        "latest": self._latest,
                        "latest_pet": self._latest_pet,
                    }
                )
                for record in new_records:
                    self.hass.bus.async_fire(
                        EVENT_NEW_PHOTO,
                        {"device": self.device_name, "duid": self.duid, **record},
                    )
        async_dispatcher_send(self.hass, signal_updated(self.duid))

    def _save_photo(self, obstacle: MapObstacle, content: bytes) -> dict[str, Any]:
        now = dt_util.now()
        day_dir = self.photo_dir / now.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        label = obstacle.label.replace(" ", "_").replace("/", "_")
        path = day_dir / f"{now:%H%M%S}_{label}_{obstacle.photo_id}.jpg"
        path.write_bytes(content)
        relative = path.relative_to(self.media_root).as_posix()
        return {
            "photo_id": obstacle.photo_id,
            "type": obstacle.obstacle_type,
            "label": obstacle.label,
            "is_pet": obstacle.obstacle_type in PET_TYPES,
            "x": obstacle.x,
            "y": obstacle.y,
            "confidence": obstacle.confidence,
            "captured_at": now.isoformat(),
            "path": str(path),
            "media_content_id": f"media-source://media_source/local/{relative}",
        }

    def read_photo(self, record: dict[str, Any]) -> bytes | None:
        """Read a saved photo from disk (runs in the executor)."""
        try:
            return Path(record["path"]).read_bytes()
        except OSError:
            return None
