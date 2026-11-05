"""Roborock Obstacle Photos: save the robot's obstacle and pet photos locally."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import PLATFORMS, ROBOROCK_DOMAIN
from .manager import ObstaclePhotoManager

type ObstaclePhotosConfigEntry = ConfigEntry[list[ObstaclePhotoManager]]


async def async_setup_entry(
    hass: HomeAssistant, entry: ObstaclePhotosConfigEntry
) -> bool:
    """Attach to every loaded core Roborock entry."""

    @callback
    def reload_this_entry() -> None:
        hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))

    coordinators = []
    for roborock_entry in hass.config_entries.async_entries(ROBOROCK_DOMAIN):
        if roborock_entry.state is ConfigEntryState.LOADED:
            coordinators.extend(roborock_entry.runtime_data.v1)
            # The core coordinators are recreated when Roborock reloads.
            roborock_entry.async_on_unload(reload_this_entry)

    if not coordinators:
        raise ConfigEntryNotReady("No loaded Roborock vacuums yet")

    managers = [ObstaclePhotoManager(hass, entry, coord) for coord in coordinators]
    managers = [manager for manager in managers if manager.supported]
    for manager in managers:
        await manager.async_start()
    entry.runtime_data = managers

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    for manager in managers:
        await manager.async_process()
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ObstaclePhotosConfigEntry
) -> bool:
    """Unload a config entry."""
    for manager in entry.runtime_data:
        manager.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
