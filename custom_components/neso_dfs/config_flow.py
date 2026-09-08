"""Config flow for the NESO DFS integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow, ConfigEntry
from homeassistant.core import callback

from .const import CONF_LIVE_ONLY, CONF_POSTCODE, CONF_ZONE, DOMAIN
from .vendor_lib import NesoError, find_zone

STEP_USER_SCHEMA = vol.Schema({vol.Optional(CONF_POSTCODE, default=""): str})


class DfsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for a postcode (or fall back to the Home Assistant location)."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            postcode = (user_input.get(CONF_POSTCODE) or "").strip()
            try:
                zone, location = await self.hass.async_add_executor_job(
                    _lookup_zone, postcode, self.hass.config.latitude, self.hass.config.longitude
                )
            except NesoError:
                errors["base"] = "cannot_connect"
            else:
                if zone is None:
                    errors["base"] = "outside_gb"
                else:
                    await self.async_set_unique_id(f"zone_{zone.number}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"DFS Zone {zone.number}",
                        data={
                            CONF_ZONE: zone.number,
                            CONF_POSTCODE: location.postcode,
                        },
                    )

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DfsOptionsFlow()


class DfsOptionsFlow(OptionsFlow):
    """Lets the user hide test events."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_LIVE_ONLY,
                    default=self.config_entry.options.get(CONF_LIVE_ONLY, False),
                ): bool
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


def _lookup_zone(postcode: str, latitude: float, longitude: float):
    """Resolve the zone from a postcode, or from the HA home coordinates."""
    if postcode:
        return find_zone(postcode=postcode)
    return find_zone(latitude=latitude, longitude=longitude)
