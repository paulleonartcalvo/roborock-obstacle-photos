"""Config flow for Roborock Obstacle Photos."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, ROBOROCK_DOMAIN


class ObstaclePhotosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-instance flow; there is nothing to configure."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setup."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if not self.hass.config_entries.async_entries(ROBOROCK_DOMAIN):
            return self.async_abort(reason="no_roborock")
        if user_input is not None:
            return self.async_create_entry(title="Roborock Obstacle Photos", data={})
        return self.async_show_form(step_id="user")
