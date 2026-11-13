"""Hue Studio: what the core Hue integration does not do (scene editing and more), as websocket commands.

Since 0.2.0 the integration is a thin client of the hue-web /api/v1: hue-web alone talks to the bridges, so there is one
connection, one traffic limiter and one scene history. This module only wires the client and the commands to Home Assistant.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import websocket
from .api_client import HueWebClient
from .const import CONF_URL, DOMAIN


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    websocket.async_register(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = HueWebClient(entry.data[CONF_URL])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
