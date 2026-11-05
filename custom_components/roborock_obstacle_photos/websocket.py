"""Websocket API used by the obstacle map card."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, PET_TYPES
from .manager import ObstaclePhotoManager, async_get_managers
from .views import photo_url

URL_EXPIRY = timedelta(hours=1)


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    websocket_api.async_register_command(hass, ws_obstacles)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/obstacles"})
@callback
def ws_obstacles(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return each vacuum's obstacles on the current map and all saved photos."""
    connection.send_result(
        msg["id"], [_vacuum_payload(hass, manager) for manager in async_get_managers(hass)]
    )


def _vacuum_payload(hass: HomeAssistant, manager: ObstaclePhotoManager) -> dict[str, Any]:
    def url(photo_id: str) -> str | None:
        if manager.photo(photo_id) is None:
            return None
        return async_sign_path(hass, photo_url(manager.duid, photo_id), URL_EXPIRY)

    current = [
        {
            "photo_id": obstacle.photo_id,
            "label": obstacle.label,
            "type": obstacle.obstacle_type,
            "is_pet": obstacle.obstacle_type in PET_TYPES,
            "confidence": obstacle.confidence,
            "x": obstacle.x,
            "y": obstacle.y,
            "captured_at": (manager.photo(obstacle.photo_id) or {}).get("captured_at"),
            "url": url(obstacle.photo_id),
        }
        for obstacle in manager.current_obstacles
    ]
    history = [
        {
            key: record.get(key)
            for key in (
                "photo_id",
                "label",
                "type",
                "is_pet",
                "confidence",
                "x",
                "y",
                "captured_at",
            )
        }
        | {"url": url(record["photo_id"])}
        for record in manager.photos()
    ]
    return {
        "duid": manager.duid,
        "name": manager.device_name,
        "current": current,
        "history": history,
    }
