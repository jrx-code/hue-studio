"""Scene memory of each bridge: the number the Hue app hides until a new scene fails."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory

from .entity import StudioEntity, add_new
from .model import capacity_percent


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.bridges

    def build():
        out = []
        for snap in (coordinator.data or {}).values():
            out += [SceneCount(coordinator, snap), SceneUse(coordinator, snap)]
        return out
    add_new(entry, coordinator, async_add_entities, build)


class _Capacity(StudioEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, snap, key):
        super().__init__(coordinator, snap, key, "bridge")
        self._attr_translation_key = key

    def resource(self):
        snap = self.snapshot
        return snap.capacity if snap else None


class SceneCount(_Capacity):
    _attr_native_unit_of_measurement = "scenes"

    def __init__(self, coordinator, snap):
        super().__init__(coordinator, snap, "scene_count")

    @property
    def native_value(self):
        return (self.resource() or {}).get("scenes")

    @property
    def extra_state_attributes(self):
        cap = self.resource() or {}
        return {"max_scenes": cap.get("max_scenes"), "lightstates": cap.get("lightstates"), "max_lightstates": cap.get("max_lightstates")}


class SceneUse(_Capacity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator, snap):
        super().__init__(coordinator, snap, "scene_use")

    @property
    def native_value(self):
        cap = self.resource() or {}
        return capacity_percent(cap.get("scenes"), cap.get("max_scenes"))
