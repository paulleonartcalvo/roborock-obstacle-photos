"""Browse saved photos in the Media panel."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .manager import ObstaclePhotoManager, async_get_manager, async_get_managers
from .views import photo_url

THUMBNAIL_EXPIRY = timedelta(days=1)


async def async_get_media_source(hass: HomeAssistant) -> MediaSource:
    """Set up the media source."""
    return ObstaclePhotosMediaSource(hass)


class ObstaclePhotosMediaSource(MediaSource):
    """Photos by vacuum, with a pets folder and one folder per day.

    Identifiers: ``<duid>``, ``<duid>/pets``, ``<duid>/day/<YYYY-MM-DD>``,
    ``<duid>/photo/<photo_id>``.
    """

    name = "Roborock Obstacle Photos"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the media source."""
        super().__init__(DOMAIN)
        self.hass = hass

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a photo to its URL."""
        manager, kind, value = self._parse(item.identifier)
        if manager is None or kind != "photo" or not (record := manager.photo(value)):
            raise Unresolvable(f"Unknown photo: {item.identifier}")
        return PlayMedia(
            photo_url(manager.duid, value), "image/jpeg", path=Path(record["path"])
        )

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Browse vacuums, folders and photos."""
        managers = async_get_managers(self.hass)
        if not item.identifier:
            if len(managers) == 1:
                return self._browse_vacuum(managers[0], title=self.name)
            return self._folder(
                None,
                self.name,
                [self._folder(m.duid, m.device_name, []) for m in managers],
            )

        manager, kind, value = self._parse(item.identifier)
        if manager is None:
            raise Unresolvable(f"Unknown vacuum: {item.identifier}")
        if kind == "":
            return self._browse_vacuum(manager, title=manager.device_name)
        if kind == "pets":
            return self._folder(
                item.identifier,
                "Pets",
                [self._photo(manager, r) for r in manager.photos(pet=True)],
            )
        if kind == "day":
            records = [
                r for r in manager.photos() if _local_day(r["captured_at"]) == value
            ]
            return self._folder(
                item.identifier, value, [self._photo(manager, r) for r in records]
            )
        raise Unresolvable(f"Not a folder: {item.identifier}")

    def _parse(self, identifier: str) -> tuple[ObstaclePhotoManager | None, str, str]:
        duid, _, rest = identifier.partition("/")
        kind, _, value = rest.partition("/")
        return async_get_manager(self.hass, duid), kind, value

    def _browse_vacuum(
        self, manager: ObstaclePhotoManager, *, title: str
    ) -> BrowseMediaSource:
        days: dict[str, int] = defaultdict(int)
        for record in manager.photos():
            days[_local_day(record["captured_at"])] += 1
        children = [
            self._folder(f"{manager.duid}/pets", "Pets", []),
            *(
                self._folder(f"{manager.duid}/day/{day}", f"{day} ({count})", [])
                for day, count in sorted(days.items(), reverse=True)
            ),
        ]
        return self._folder(manager.duid, title, children)

    def _folder(
        self, identifier: str | None, title: str, children: list[BrowseMediaSource]
    ) -> BrowseMediaSource:
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=identifier,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.IMAGE,
            title=title,
            can_play=False,
            can_expand=True,
            children=children,
            children_media_class=MediaClass.IMAGE,
        )

    def _photo(
        self, manager: ObstaclePhotoManager, record: dict[str, Any]
    ) -> BrowseMediaSource:
        captured = dt_util.as_local(dt_util.parse_datetime(record["captured_at"]))
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{manager.duid}/photo/{record['photo_id']}",
            media_class=MediaClass.IMAGE,
            media_content_type="image/jpeg",
            title=f"{captured:%b %-d %H:%M} · {record['label']}",
            can_play=True,
            can_expand=False,
            thumbnail=async_sign_path(
                self.hass,
                photo_url(manager.duid, record["photo_id"]),
                THUMBNAIL_EXPIRY,
            ),
        )


def _local_day(captured_at: str) -> str:
    return dt_util.as_local(dt_util.parse_datetime(captured_at)).strftime("%Y-%m-%d")
