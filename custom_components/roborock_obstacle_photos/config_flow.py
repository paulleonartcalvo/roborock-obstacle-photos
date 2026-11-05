"""Config flow for Roborock Obstacle Photos."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import CONF_RETENTION_DAYS, DOMAIN, ROBOROCK_DOMAIN


class ObstaclePhotosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-instance flow; there is nothing to configure."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return ObstaclePhotosOptionsFlow()

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


class ObstaclePhotosOptionsFlow(OptionsFlow):
    """How long to keep photos."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_RETENTION_DAYS: int(user_input[CONF_RETENTION_DAYS])}
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_RETENTION_DAYS,
                        default=self.config_entry.options.get(CONF_RETENTION_DAYS, 0),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=3650,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="days",
                        )
                    )
                }
            ),
        )
