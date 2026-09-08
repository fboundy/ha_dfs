"""The NESO Demand Flexibility Service integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_LIVE_ONLY, CONF_ZONE
from .coordinator import DfsCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

type DfsConfigEntry = ConfigEntry[DfsCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: DfsConfigEntry) -> bool:
    coordinator = DfsCoordinator(
        hass,
        entry,
        zone=entry.data[CONF_ZONE],
        live_only=entry.options.get(CONF_LIVE_ONLY, False),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DfsConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: DfsConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
