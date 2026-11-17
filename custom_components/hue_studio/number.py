"""Motion sensitivity (0..the sensor's own maximum): a setting the Hue app has and core hue does not expose."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import callback

from .coordinator import seg
from .dynamics import AreaDynamics
from .entity import Optimistic, StudioEntity, add_new


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.bridges

    def build():
        out = [MotionSensitivity(coordinator, snap, rid, s)
               for snap in (coordinator.data or {}).values() for rid, s in snap.motion_sensors().items()
               if isinstance(s.get("sensitivity_max"), int)]
        out += [DynamicSpeed(coordinator, snap, area, row)
                for snap in (coordinator.data or {}).values() for area, row in snap.dynamic_areas().items()]
        return out
    add_new(entry, coordinator, async_add_entities, build)


class MotionSensitivity(Optimistic, StudioEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0
    _attr_native_step = 1
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, coordinator, snap, rid, sensor):
        super().__init__(coordinator, snap, "motion_sensitivity", rid, device_rid=sensor.get("id"))
        self.name_for("sensitivity", sensor.get("name"))

    def resource(self):
        snap = self.snapshot
        return snap.motion_sensors().get(self.rid) if snap else None

    @property
    def native_max_value(self) -> float:
        return float((self.resource() or {}).get("sensitivity_max") or 4)

    @property
    def native_value(self):
        return self.shown((self.resource() or {}).get("sensitivity"))

    @callback
    def _handle_coordinator_update(self) -> None:
        self.pending_check((self.resource() or {}).get("sensitivity"))
        super()._handle_coordinator_update()

    async def async_set_native_value(self, value: float) -> None:
        level = int(round(value))
        await self.coordinator.async_write("PUT", f"/bridges/{seg(self.bridge)}/motion/{seg(self.rid)}", {"sensitivity": level})
        self.pending_set(level)


class DynamicSpeed(Optimistic, AreaDynamics, NumberEntity):
    """Speed of the palette of the active scene of the area, 1..100 %; the bridge keeps it in the scene."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator, snap, area, row):
        super().__init__(coordinator, snap, "dynamic_speed", area, row)
        self.name_for("dynamic_speed", row.get("name"))

    def _reported(self):
        s = self.scene()
        if not s or not s.get("palette") or not isinstance(s.get("speed"), (int, float)):
            return None
        return max(1, round(s["speed"] * 100))

    @property
    def native_value(self):
        return self.shown(self._reported())

    @callback
    def _handle_coordinator_update(self) -> None:
        self.pending_check(self._reported())
        super()._handle_coordinator_update()

    async def async_set_native_value(self, value: float) -> None:
        s = self.dynamic_scene()
        pct = int(round(value))
        await self.coordinator.async_write("PUT", f"/bridges/{seg(self.bridge)}/scene/{seg(s['id'])}", {"speed": pct / 100})
        self.pending_set(pct)
