"""Photo gallery: a media player that browses and shows the saved photos."""

from __future__ import annotations

from typing import Any

from homeassistant.components import media_source
from homeassistant.components.homeassistant.exposed_entities import (
    async_expose_entity,
)
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ObstaclePhotosConfigEntry
from .const import DOMAIN
from .entity import ObstaclePhotoEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ObstaclePhotosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the gallery."""
    async_add_entities(
        PhotoGallery(manager, "photo_gallery") for manager in entry.runtime_data
    )


class PhotoGallery(ObstaclePhotoEntity, MediaPlayerEntity):
    """Shows the newest photo, or one picked with Browse media."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.BROWSE_MEDIA | MediaPlayerEntityFeature.PLAY_MEDIA
    )
    _attr_media_content_type = MediaType.IMAGE
    _attr_state = MediaPlayerState.IDLE

    _selected: str | None = None
    _newest: str | None = None

    async def async_added_to_hass(self) -> None:
        """Keep the gallery away from voice assistants unless the user opts in."""
        await super().async_added_to_hass()
        if self.registry_entry and "conversation" not in self.registry_entry.options:
            async_expose_entity(self.hass, "conversation", self.entity_id, False)

    def _shown(self) -> dict[str, Any] | None:
        if self._selected and (record := self.manager.photo(self._selected)):
            return record
        return self.manager.latest()

    @callback
    def _handle_update(self) -> None:
        # A new photo replaces whatever was picked by hand.
        newest = (self.manager.latest() or {}).get("photo_id")
        if newest != self._newest:
            self._newest = newest
            self._selected = None
        super()._handle_update()

    @property
    def media_content_id(self) -> str | None:
        """Photo being shown."""
        record = self._shown()
        return record["photo_id"] if record else None

    @property
    def media_title(self) -> str | None:
        """Label and confidence of the photo."""
        if (record := self._shown()) is None:
            return None
        confidence = record.get("confidence")
        return f"{record['label']} · {confidence}%" if confidence else record["label"]

    @property
    def media_image_hash(self) -> str | None:
        """Change the picture whenever the shown photo changes."""
        return self.media_content_id

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """When the photo was taken."""
        if (record := self._shown()) is None:
            return None
        return {"captured_at": record["captured_at"], "is_pet": record["is_pet"]}

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """Return the shown photo."""
        if (record := self._shown()) is None:
            return None, None
        content = await self.hass.async_add_executor_job(
            self.manager.read_photo, record
        )
        return content, "image/jpeg"

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse this vacuum's photos."""
        return await media_source.async_browse_media(
            self.hass,
            media_content_id or f"{media_source.URI_SCHEME}{DOMAIN}/{self.manager.duid}",
        )

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Show a photo picked in the browser."""
        prefix = f"{media_source.URI_SCHEME}{DOMAIN}/{self.manager.duid}/photo/"
        photo_id = media_id.removeprefix(prefix)
        if photo_id == media_id or self.manager.photo(photo_id) is None:
            raise HomeAssistantError(f"Not a photo from this vacuum: {media_id}")
        self._selected = photo_id
        self.async_write_ha_state()
