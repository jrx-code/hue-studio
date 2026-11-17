"""Diagnostics: what the coordinators hold, without the hue-web address and with counts instead of whole states."""
from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data

from .const import CONF_URL


async def async_get_config_entry_diagnostics(hass, entry) -> dict:
    rt = entry.runtime_data
    bridges = {}
    for name, snap in (rt.bridges.data or {}).items():
        bridges[name] = {"bridge": {k: snap.info.get(k) for k in ("model", "sw", "pinned")}, "counts": snap.state.get("counts"),
                         "capacity": snap.capacity}
    return {
        "entry": async_redact_data(dict(entry.data), {CONF_URL}),
        "bridges_update_success": rt.bridges.last_update_success,
        "hub_update_success": rt.hub.last_update_success,
        "bridges": bridges,
        "hub_scenes": None if rt.hub.data is None else len(rt.hub.data),
        "streams_up": sorted(rt.events.up) if rt.events else [],
        "stream_refreshes": rt.events.refreshes if rt.events else 0,
        "poll_seconds": rt.bridges.update_interval.total_seconds() if rt.bridges.update_interval else None,
    }
