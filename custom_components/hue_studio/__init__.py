"""Hue Studio: what the core Hue integration does not do, through hue-web (the one process that talks to the bridges).

Entities (hub scenes, smart scene switches, scene capacity, settings core hue lacks) read two coordinators; the websocket
commands of 0.2 stay for App Hub. hue-web owns the bridge connections, so there is one traffic limiter and one history.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import services, websocket
from .aio_client import AsyncHueWeb
from .api_client import HueWebClient
from .const import CONF_URL, DOMAIN, HUB_DEVICE, PLATFORMS
from .coordinator import BridgesCoordinator, HubCoordinator, StudioRuntime
from .cleanup import RegistryCleanup
from .events import EventStreams

_LOGGER = logging.getLogger(__name__)

type StudioConfigEntry = ConfigEntry[StudioRuntime]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    websocket.async_register(hass)
    services.async_register(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: StudioConfigEntry) -> bool:
    url = entry.data[CONF_URL]
    api = AsyncHueWeb(async_get_clientsession(hass), url)
    rt = StudioRuntime(api, HueWebClient(url), BridgesCoordinator(hass, entry, api), HubCoordinator(hass, entry, api))
    await rt.bridges.async_config_entry_first_refresh()    # raises ConfigEntryNotReady while hue-web is down
    await rt.hub.async_config_entry_first_refresh()
    entry.runtime_data = rt
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = rt.client     # the websocket commands look the client up here
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, HUB_DEVICE)}, name="Hue Web", manufacturer="JI ENGINEERING",
        model="hue-web", entry_type=dr.DeviceEntryType.SERVICE, configuration_url=url)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    rt.events = EventStreams(hass, entry, rt)
    rt.events.start()
    rt.cleanup = RegistryCleanup(hass, entry, rt)
    rt.cleanup.start()
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entries of 0.1 talked to one bridge with its own key; 0.2+ talks to hue-web. Nothing carries over."""
    if entry.version < 2:
        _LOGGER.error("Hue Studio entry '%s' is from 0.1 (direct bridge access): remove it and add Hue Web instead", entry.title)
        return False
    return True


async def async_unload_entry(hass: HomeAssistant, entry: StudioConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return ok
