"""Config flow for the NESO DFS integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_LIVE_ONLY, CONF_PARTICIPANT, CONF_POSTCODE, CONF_ZONE, DOMAIN
from .vendor_lib import NesoError, find_zone
from .vendor_lib.bids import fetch_participants

STEP_USER_SCHEMA = vol.Schema({vol.Optional(CONF_POSTCODE, default=""): str})


class DfsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Resolve the zone, then offer a participant to follow."""

    VERSION = 1

    def __init__(self) -> None:
        self._zone: int | None = None
        self._postcode: str | None = None

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
                    self._zone = zone.number
                    self._postcode = location.postcode
                    return await self.async_step_participant()

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def async_step_participant(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Offer the participants that actually bid into this zone. Skippable."""
        if user_input is not None:
            participant = (user_input.get(CONF_PARTICIPANT) or "").strip()
            return self.async_create_entry(
                title=f"DFS Zone {self._zone}",
                data={CONF_ZONE: self._zone, CONF_POSTCODE: self._postcode},
                options={CONF_PARTICIPANT: participant} if participant else {},
            )

        schema = vol.Schema(
            {
                vol.Optional(CONF_PARTICIPANT, default=""): await _participant_selector(
                    self.hass, self._zone
                )
            }
        )
        return self.async_show_form(
            step_id="participant",
            data_schema=schema,
            description_placeholders={"zone": str(self._zone)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DfsOptionsFlow()


class DfsOptionsFlow(OptionsFlow):
    """Lets the user hide test events and follow one participant's results."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(CONF_PARTICIPANT, "")
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_LIVE_ONLY,
                    default=self.config_entry.options.get(CONF_LIVE_ONLY, False),
                ): bool,
                vol.Optional(CONF_PARTICIPANT, default=current): await _participant_selector(
                    self.hass, self.config_entry.data[CONF_ZONE], current
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


async def _participant_selector(hass, zone: int, current: str = "") -> SelectSelector:
    """Dropdown of participants that have bid into this zone, plus a 'None' entry."""
    try:
        participants = await hass.async_add_executor_job(fetch_participants, zone)
    except NesoError:
        participants = []
    if current and current not in participants:
        participants = sorted([*participants, current], key=str.casefold)

    options = [SelectOptionDict(value="", label="None")]
    options += [SelectOptionDict(value=name, label=name) for name in participants]
    return SelectSelector(
        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN, custom_value=True)
    )


def _lookup_zone(postcode: str, latitude: float, longitude: float):
    """Resolve the zone from a postcode, or from the HA home coordinates."""
    if postcode:
        return find_zone(postcode=postcode)
    return find_zone(latitude=latitude, longitude=longitude)
