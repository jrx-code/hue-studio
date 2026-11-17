"""Smart scenes (Hue schedules) as switches: on while the schedule runs. Core hue can start one, not stop it.

The switch sits on core hue's room or zone device (where core hue keeps the smart scene's own scene entity), so it is
named by the smart scene alone; without core hue it lands on the bridge device and carries the area in its name.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback

from .coordinator import seg
from .dynamics import AreaDynamics
from .entity import Optimistic, StudioEntity, add_new
from .model import smart_scene_active


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.bridges

    def build():
        out = [SmartSceneSwitch(coordinator, snap, rid)
               for snap in (coordinator.data or {}).values() for rid in snap.smart_scenes()]
        out += [DynamicSwitch(coordinator, snap, area, row)
                for snap in (coordinator.data or {}).values() for area, row in snap.dynamic_areas().items()]
        return out
    add_new(entry, coordinator, async_add_entities, build)


class SmartSceneSwitch(StudioEntity, SwitchEntity):
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, snap, rid):
        super().__init__(coordinator, snap, "smart_scene", rid, device_rid=(snap.smart_scenes().get(rid) or {}).get("group"))
        if self.on_own_device:        # "<name> schedule": core hue's scene entity of the same smart scene has the bare name
            self._attr_translation_key = "schedule"
            self._attr_translation_placeholders = {"name": (snap.smart_scenes().get(rid) or {}).get("name") or rid}
        self._pending: bool | None = None       # what the last write asked for, until the bridge reports it
        self._waited = 0                        # refreshes seen since that write: give up on the guess after two

    def resource(self):
        snap = self.snapshot
        return snap.smart_scenes().get(self.rid) if snap else None

    @property
    def name(self):
        s = self.resource() or {}
        if self.on_own_device:
            self._attr_translation_placeholders = {"name": s.get("name") or self.rid}
            return super().name
        area = (self.snapshot.area_names().get(s.get("group")) if self.snapshot else None)
        return f"{s.get('name') or self.rid}" + (f" ({area})" if area else "")

    @property
    def is_on(self):
        if self._pending is not None:
            return self._pending
        s = self.resource()
        return smart_scene_active(s) if s else None

    @property
    def extra_state_attributes(self):
        s = self.resource() or {}
        return {"smart_scene_id": self.rid, "bridge": self.bridge, "area_id": s.get("group"), "state": s.get("state")}

    @callback
    def _handle_coordinator_update(self) -> None:
        s = self.resource()
        if self._pending is not None:
            self._waited += 1
            if (s is not None and smart_scene_active(s) == self._pending) or self._waited >= 2:
                self._pending = None
        super()._handle_coordinator_update()

    async def _act(self, action: str, on: bool) -> None:
        await self.coordinator.async_write("POST", f"/bridges/{seg(self.bridge)}/smart_scene/{seg(self.rid)}/{action}")
        self._pending, self._waited = on, 0
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        await self._act("activate", True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._act("deactivate", False)


class DynamicSwitch(Optimistic, AreaDynamics, SwitchEntity):
    """On while the active scene of the area plays its palette; on plays it, off holds the current colours."""

    _attr_icon = "mdi:palette"

    def __init__(self, coordinator, snap, area, row):
        super().__init__(coordinator, snap, "dynamic", area, row)
        self.name_for("dynamic", row.get("name"))

    @property
    def is_on(self):
        s = self.scene()
        return self.shown(bool(s and s.get("playing")))

    @callback
    def _handle_coordinator_update(self) -> None:
        s = self.scene()
        self.pending_check(bool(s and s.get("playing")))
        super()._handle_coordinator_update()

    async def _recall(self, action: str, on: bool) -> None:
        s = self.dynamic_scene()
        await self.coordinator.async_write("POST", f"/bridges/{seg(self.bridge)}/scene/{seg(s['id'])}/recall?action={action}")
        self.pending_set(on)

    async def async_turn_on(self, **kwargs) -> None:
        await self._recall("dynamic_palette", True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._recall("static", False)

