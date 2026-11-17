"""Dynamics of the active scene of a room or zone: a switch that plays or holds its palette, a number for its speed.

Core hue can start a scene dynamic, but shows no state for it and cannot hold it or change the speed afterwards. Both
entities sit on core hue's room or zone device; zone entities start disabled (zones overlap the rooms).
"""
from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError

from .entity import StudioEntity


class AreaDynamics(StudioEntity):
    def __init__(self, coordinator, snap, kind, area, row):
        super().__init__(coordinator, snap, kind, area, device_rid=area)
        self.area = area
        self._attr_entity_registry_enabled_default = row.get("kind") != "zone"

    def resource(self):
        snap = self.snapshot
        return (snap.dynamic_areas().get(self.area) if snap else None)

    def scene(self) -> dict | None:
        snap = self.snapshot
        return snap.active_scene(self.area) if snap else None

    def dynamic_scene(self) -> dict:
        s = self.scene()
        if not s or not s.get("palette"):
            name = (self.resource() or {}).get("name") or self.area
            raise HomeAssistantError(f"{name}: no active scene with a colour palette")
        return s

    @property
    def extra_state_attributes(self):
        s = self.scene() or {}
        return {"active_scene": s.get("name"), "scene_id": s.get("id"), "can_play": bool(s.get("palette"))}
