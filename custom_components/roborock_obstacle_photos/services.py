"""Services to check whether the robot drove through an area since a moment."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN
from .manager import ObstaclePhotoManager, async_get_managers

ATTR_NAME = "name"
ATTR_JOB = "job"
ATTR_ZONE = "zone"
ATTR_VACUUM = "vacuum"

_BASE = {
    vol.Required(ATTR_NAME): cv.string,
    vol.Optional(ATTR_JOB, default=""): cv.string,
    vol.Optional(ATTR_VACUUM): cv.string,
}
MARK_SCHEMA = vol.Schema(_BASE)
CROSSED_SCHEMA = vol.Schema(
    {**_BASE, vol.Required(ATTR_ZONE): vol.All([vol.Coerce(int)], vol.Length(min=4, max=4))}
)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register mark_path and path_crossed."""

    def manager_for(call: ServiceCall) -> ObstaclePhotoManager:
        wanted = call.data.get(ATTR_VACUUM)
        for manager in async_get_managers(hass):
            if wanted in (None, manager.duid, manager.device_name):
                return manager
        raise ServiceValidationError(f"No vacuum with obstacle photos found ({wanted or 'any'})")

    async def mark_path(call: ServiceCall) -> ServiceResponse:
        return await manager_for(call).async_mark_path(
            call.data[ATTR_NAME], call.data[ATTR_JOB]
        )

    async def path_crossed(call: ServiceCall) -> ServiceResponse:
        return await manager_for(call).async_path_crossed(
            call.data[ATTR_NAME], call.data[ATTR_ZONE], call.data[ATTR_JOB]
        )

    hass.services.async_register(
        DOMAIN, "mark_path", mark_path, MARK_SCHEMA, SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, "path_crossed", path_crossed, CROSSED_SCHEMA, SupportsResponse.ONLY
    )
