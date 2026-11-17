"""Registry cleanup: entities of resources that are gone from hue-web (a deleted hub scene, smart scene, sensor or light).

Only after two complete refreshes in a row miss the resource, so a bridge that answered half a state, or a resource
being re-paired, never loses its entity (and its entity_id, history and automations) on one bad read.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import entity_registry as er

from .const import HUB_DEVICE
from .entity import bridge_key


def expected_ids(rt) -> set[str] | None:
    """Every unique id the platforms would create now; None while either coordinator lacks a complete answer."""
    if not rt.bridges.last_update_success or not rt.hub.last_update_success or rt.bridges.data is None:
        return None
    out = {f"{HUB_DEVICE}_online"}
    for snap in rt.bridges.data.values():
        bk = bridge_key(snap)
        out |= {f"{bk}_scene_count_bridge", f"{bk}_scene_use_bridge", f"{bk}_scenes_unreferenced_bridge"}
        if snap.updates:
            out.add(f"{bk}_firmware_bridge")
        out |= {f"{bk}_smart_scene_{rid}" for rid in snap.smart_scenes()}
        out |= {f"{bk}_motion_sensitivity_{rid}" for rid, s in snap.motion_sensors().items() if isinstance(s.get("sensitivity_max"), int)}
        out |= {f"{bk}_powerup_{rid}" for rid in snap.powerup_lights()}
        out |= {f"{bk}_{k}_{rid}" for rid in snap.dynamic_areas() for k in ("dynamic", "dynamic_speed")}
    out |= {f"{HUB_DEVICE}_scene_{sid}" for sid in (rt.hub.data or {})}
    return out


class RegistryCleanup:
    def __init__(self, hass, entry, rt) -> None:
        self.hass, self.entry, self.rt = hass, entry, rt
        self.missing: dict[str, int] = {}
        self.removed: list[str] = []
        self._reads = (-1, -1)

    @callback
    def check(self) -> None:
        want = expected_ids(self.rt)
        reads = (self.rt.bridges.reads, self.rt.hub.reads)
        if want is None or reads == self._reads:      # nothing new was read since the last look
            return
        self._reads = reads
        reg = er.async_get(self.hass)
        seen = set()
        for ent in er.async_entries_for_config_entry(reg, self.entry.entry_id):
            if ent.unique_id in want:
                continue
            seen.add(ent.unique_id)
            self.missing[ent.unique_id] = self.missing.get(ent.unique_id, 0) + 1
            if self.missing[ent.unique_id] >= 2:
                reg.async_remove(ent.entity_id)
                self.removed.append(ent.entity_id)
                self.missing.pop(ent.unique_id, None)
        for uid in list(self.missing):
            if uid not in seen:
                self.missing.pop(uid)

    def start(self) -> None:
        self.entry.async_on_unload(self.rt.bridges.async_add_listener(self.check))
        self.entry.async_on_unload(self.rt.hub.async_add_listener(self.check))
        # A refresh that changed nothing calls no listener (always_update=False): look again every minute.
        self.entry.async_on_unload(async_track_time_interval(self.hass, lambda _now: self.check(), timedelta(seconds=60)))
