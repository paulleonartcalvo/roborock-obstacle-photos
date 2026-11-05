"""Roborock Obstacle Photos: save the robot's obstacle and pet photos locally."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DATA_VIEW_REGISTERED, PLATFORMS, ROBOROCK_DOMAIN
from .manager import ObstaclePhotoManager
from .views import ObstaclePhotoView

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

    # 0.1.0 created its own copy of the vacuum device; move its entities to the
    # core integration's device and drop the copy.
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    vacuum_devices = {manager.duid: manager.device_entry for manager in managers}
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        for entity in er.async_entries_for_device(entities, device.id):
            target = next(
                (
                    vacuum
                    for duid, vacuum in vacuum_devices.items()
                    if vacuum and entity.unique_id.startswith(f"{duid}_")
                ),
                None,
            )
            if target:
                entities.async_update_entity(entity.entity_id, device_id=target.id)
        devices.async_remove_device(device.id)

    if not hass.data.get(DATA_VIEW_REGISTERED):
        hass.http.register_view(ObstaclePhotoView())
        hass.data[DATA_VIEW_REGISTERED] = True

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
