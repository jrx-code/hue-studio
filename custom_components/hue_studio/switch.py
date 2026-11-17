"""Smart scenes (Hue schedules) as switches: on while the schedule runs. Core hue can start one, not stop it."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback

from .coordinator import seg
from .entity import StudioEntity, add_new
from .model import smart_scene_active


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.bridges

    def build():
        return [SmartSceneSwitch(coordinator, snap, rid)
                for snap in (coordinator.data or {}).values() for rid in snap.smart_scenes()]
    add_new(entry, coordinator, async_add_entities, build)


class SmartSceneSwitch(StudioEntity, SwitchEntity):
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, snap, rid):
        super().__init__(coordinator, snap, "smart_scene", rid)
        self._pending: bool | None = None       # what the last write asked for, until the bridge reports it
        self._waited = 0                        # refreshes seen since that write: give up on the guess after two

    def resource(self):
        snap = self.snapshot
        return snap.smart_scenes().get(self.rid) if snap else None

    @property
    def name(self):
        s = self.resource() or {}
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
