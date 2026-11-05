"""Base entity for Roborock Obstacle Photos."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import ROBOROCK_DOMAIN, signal_updated
from .manager import ObstaclePhotoManager


class ObstaclePhotoEntity(Entity):
    """Entity attached to the existing Roborock vacuum device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: ObstaclePhotoManager, key: str) -> None:
        """Initialize the entity."""
        self.manager = manager
        self._attr_translation_key = key
        self._attr_unique_id = f"{manager.duid}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(ROBOROCK_DOMAIN, manager.duid)}
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to photo updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_updated(self.manager.duid), self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
