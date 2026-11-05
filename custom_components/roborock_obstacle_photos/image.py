"""Latest obstacle and pet photo images."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import ObstaclePhotosConfigEntry
from .entity import ObstaclePhotoEntity
from .manager import ObstaclePhotoManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ObstaclePhotosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the photo image entities."""
    async_add_entities(
        LatestPhotoImage(hass, manager, pet=pet)
        for manager in entry.runtime_data
        for pet in (False, True)
    )


class LatestPhotoImage(ObstaclePhotoEntity, ImageEntity):
    """The newest photo the robot took of an obstacle (or of a pet)."""

    _attr_content_type = "image/jpeg"

    def __init__(
        self, hass: HomeAssistant, manager: ObstaclePhotoManager, *, pet: bool
    ) -> None:
        """Initialize the image entity."""
        ObstaclePhotoEntity.__init__(
            self, manager, "latest_pet_photo" if pet else "latest_obstacle_photo"
        )
        ImageEntity.__init__(self, hass)
        self._pet = pet
        self._record = manager.latest(pet=pet)
        self._attr_image_last_updated = self._captured_at()

    def _captured_at(self) -> datetime | None:
        if self._record is None:
            return None
        return dt_util.parse_datetime(self._record["captured_at"])

    @callback
    def _handle_update(self) -> None:
        record = self.manager.latest(pet=self._pet)
        if record is not self._record:
            self._record = record
            self._attr_image_last_updated = self._captured_at()
        super()._handle_update()

    @property
    def available(self) -> bool:
        """Only available once a photo exists."""
        return self._record is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Describe the photo."""
        if self._record is None:
            return None
        return {
            key: self._record[key]
            for key in ("label", "type", "x", "y", "captured_at", "media_content_id")
        }

    async def async_image(self) -> bytes | None:
        """Return the photo bytes."""
        if self._record is None:
            return None
        return await self.hass.async_add_executor_job(
            self.manager.read_photo, self._record
        )
