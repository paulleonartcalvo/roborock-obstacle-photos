"""Constants for Roborock Obstacle Photos."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "roborock_obstacle_photos"
ROBOROCK_DOMAIN = "roborock"

PLATFORMS = [Platform.BUTTON, Platform.IMAGE, Platform.MEDIA_PLAYER, Platform.SENSOR]

EVENT_NEW_PHOTO = f"{DOMAIN}_new_photo"

CARD_URL = f"/{DOMAIN}/roborock-obstacle-map-card.js"

STORAGE_VERSION = 1

CONF_RETENTION_DAYS = "retention_days"
CONF_OBSTACLE_TYPES = "obstacle_types"
PRUNE_INTERVAL = timedelta(hours=6)

# Obstacle type codes the robot uses for animals (see vacuum-map-parser-roborock).
PET_TYPES = frozenset({49, 50})


def signal_updated(duid: str) -> str:
    """Dispatcher signal sent when a device's photos change."""
    return f"{DOMAIN}_updated_{duid}"
