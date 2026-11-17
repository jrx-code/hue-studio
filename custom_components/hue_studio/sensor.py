"""Scene memory of each bridge: the number the Hue app hides until a new scene fails."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import callback

from .entity import StudioEntity, add_new
from .model import capacity_percent, scene_label, scene_refs
from .refs import ha_scene_refs

LIST_MAX = 60      # names listed in the attribute; the state counts them all


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.bridges

    def build():
        out = []
        for snap in (coordinator.data or {}).values():
            out += [SceneCount(coordinator, snap), SceneUse(coordinator, snap), UnreferencedScenes(coordinator, snap)]
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


class UnreferencedScenes(StudioEntity, SensorEntity):
    """Bridge scenes nothing recalls: no smart scene, hue-web reaction, native sensor or switch rule, HA automation or
    script. Candidates for delete_scenes when the bridge runs out of scene memory; a dashboard button or the Hue app's
    scene list are not seen, so the list is for review, not for deleting blindly."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "scenes"
    _attr_translation_key = "scenes_unreferenced"
    _attr_icon = "mdi:image-off-outline"

    def __init__(self, coordinator, snap):
        super().__init__(coordinator, snap, "scenes_unreferenced", "bridge")
        self._found: list[dict] | None = None

    def resource(self):
        snap = self.snapshot
        return scene_refs(snap) if snap else None

    def _compute(self) -> None:
        snap, refs = self.snapshot, self.resource()
        if snap is None or refs is None:
            self._found = None
            return
        scenes = snap.state.get("scenes") or []
        ha = ha_scene_refs(self.hass, [x["id"] for x in scenes if x.get("id") not in refs])
        self._found = [x for x in scenes if x.get("id") and x["id"] not in refs and x["id"] not in ha]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._compute()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._compute()
        super()._handle_coordinator_update()

    @property
    def native_value(self):
        return None if self._found is None else len(self._found)

    @property
    def extra_state_attributes(self):
        if self._found is None:
            return None
        snap = self.snapshot
        rows = sorted(scene_label(snap, x) for x in self._found)
        return {"scenes": rows[:LIST_MAX], "more": max(0, len(rows) - LIST_MAX)}
