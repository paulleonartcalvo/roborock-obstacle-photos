"""Obstacles on the current map that have photos."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ObstaclePhotosConfigEntry
from .const import PET_TYPES
from .entity import ObstaclePhotoEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ObstaclePhotosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the obstacle sensor."""
    async_add_entities(
        MapObstaclesSensor(manager, "map_obstacles") for manager in entry.runtime_data
    )


class MapObstaclesSensor(ObstaclePhotoEntity, SensorEntity):
    """Count of photographed obstacles on the current map, with details."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int:
        """Number of photographed obstacles on the current map."""
        return len(self.manager.current_obstacles)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """List each obstacle and how many photos are saved overall."""
        return {
            "obstacles": [
                {
                    "label": obstacle.label,
                    "type": obstacle.obstacle_type,
                    "is_pet": obstacle.obstacle_type in PET_TYPES,
                    "x": obstacle.x,
                    "y": obstacle.y,
                    "photo_id": obstacle.photo_id,
                }
                for obstacle in self.manager.current_obstacles
            ],
            "saved_photos": self.manager.photo_count,
        }
