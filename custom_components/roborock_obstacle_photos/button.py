"""Button to fetch photos right away."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ObstaclePhotosConfigEntry
from .entity import ObstaclePhotoEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ObstaclePhotosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the refresh button."""
    async_add_entities(
        RefreshPhotosButton(manager, "refresh_photos") for manager in entry.runtime_data
    )


class RefreshPhotosButton(ObstaclePhotoEntity, ButtonEntity):
    """Fetch the latest map and any new photos now."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        """Refresh the map and download new photos."""
        await self.manager.async_refresh()
