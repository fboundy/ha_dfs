"""Config flow for the NESO DFS integration."""

from __future__ import annotations

import logging
from functools import partial
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

from .const import (
    CONF_LIVE_ONLY,
    CONF_PARTICIPANT,
    CONF_POSTCODE,
    CONF_ZONE,
    DOMAIN,
    as_participant_list,
)
from .vendor_lib import NesoError, find_zone
from .vendor_lib.bids import fetch_participants

_LOGGER = logging.getLogger(__name__)

ZONE_NUMBERS = range(1, 13)
# Cached under /config so the boundaries survive a restart; a container's home directory
# does not, and re-downloading them during setup is what makes this step fail.
CACHE_SUBDIR = ".neso_dfs"

STEP_POSTCODE_SCHEMA = vol.Schema({vol.Required(CONF_POSTCODE): str})
STEP_ZONE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ZONE): SelectSelector(
            SelectSelectorConfig(
                options=[SelectOptionDict(value=str(n), label=f"Zone {n}") for n in ZONE_NUMBERS],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
    }
)


class DfsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Choose a zone by location, postcode or directly, then offer participants to follow."""

    VERSION = 1

    def __init__(self) -> None:
        self._zone: int | None = None
        self._postcode: str | None = None
        self._errors: dict[str, str] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["home", "postcode", "zone"])

    async def async_step_home(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Use the coordinates Home Assistant already holds for this instance."""
        try:
            zone, location = await self.hass.async_add_executor_job(
                partial(
                    find_zone,
                    latitude=self.hass.config.latitude,
                    longitude=self.hass.config.longitude,
                    cache=self.hass.config.path(CACHE_SUBDIR),
                )
            )
        except NesoError as err:
            _LOGGER.error("DFS zone lookup from the Home Assistant location failed: %s", err)
            self._errors = {"base": "cannot_connect"}
        else:
            if zone is None:
                self._errors = {"base": "outside_gb"}
            else:
                return await self._resolved(zone.number, location.postcode)

        # Nothing usable from the home location, so fall through to asking for a postcode.
        return await self.async_step_postcode()

    async def async_step_postcode(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors, self._errors = self._errors, {}

        if user_input is not None:
            postcode = (user_input.get(CONF_POSTCODE) or "").strip()
            try:
                zone, location = await self.hass.async_add_executor_job(
                    partial(find_zone, postcode=postcode, cache=self.hass.config.path(CACHE_SUBDIR))
                )
            except NesoError as err:
                _LOGGER.error("DFS zone lookup for postcode %s failed: %s", postcode, err)
                errors = {"base": "not_found" if "not found" in str(err) else "cannot_connect"}
            else:
                if zone is None:
                    errors = {"base": "outside_gb"}
                else:
                    return await self._resolved(zone.number, location.postcode)

        return self.async_show_form(
            step_id="postcode", data_schema=STEP_POSTCODE_SCHEMA, errors=errors
        )

    async def async_step_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick the zone number directly, for anyone who already knows it."""
        if user_input is not None:
            return await self._resolved(int(user_input[CONF_ZONE]), None)
        return self.async_show_form(step_id="zone", data_schema=STEP_ZONE_SCHEMA)

    async def _resolved(self, zone: int, postcode: str | None) -> ConfigFlowResult:
        await self.async_set_unique_id(f"zone_{zone}")
        self._abort_if_unique_id_configured()
        self._zone = zone
        self._postcode = postcode
        return await self.async_step_participant()

    async def async_step_participant(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Offer the participants that actually bid into this zone. Skippable."""
        if user_input is not None:
            participants = user_input.get(CONF_PARTICIPANT) or []
            return self.async_create_entry(
                title=f"DFS Zone {self._zone}",
                data={CONF_ZONE: self._zone, CONF_POSTCODE: self._postcode},
                options={CONF_PARTICIPANT: participants} if participants else {},
            )

        schema = vol.Schema(
            {
                vol.Optional(CONF_PARTICIPANT, default=[]): await _participant_selector(
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
    """Lets the user hide test events and follow participants' results."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = as_participant_list(self.config_entry.options.get(CONF_PARTICIPANT))
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


async def _participant_selector(hass, zone: int, current: list[str] | None = None) -> SelectSelector:
    """Multi-select of the participants that have bid into this zone."""
    try:
        participants = await hass.async_add_executor_job(fetch_participants, zone)
    except NesoError:
        participants = []
    missing = [name for name in (current or []) if name not in participants]
    if missing:
        participants = sorted([*participants, *missing], key=str.casefold)

    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=name, label=name) for name in participants],
            mode=SelectSelectorMode.DROPDOWN,
            multiple=True,
            custom_value=True,
        )
    )
