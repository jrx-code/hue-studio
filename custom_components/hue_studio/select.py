"""What a light does when power comes back: a Hue app setting core hue does not expose. Off by default (one per light)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback

from .coordinator import seg
from .entity import Optimistic, StudioEntity, add_new
from .model import POWERUP_PRESETS


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.bridges

    def build():
        return [PowerUp(coordinator, snap, rid, light)
                for snap in (coordinator.data or {}).values() for rid, light in snap.powerup_lights().items()]
    add_new(entry, coordinator, async_add_entities, build)


class PowerUp(Optimistic, StudioEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_options = POWERUP_PRESETS
    _attr_icon = "mdi:power-plug-outline"

    def __init__(self, coordinator, snap, rid, light):
        super().__init__(coordinator, snap, "powerup", rid, device_rid=light.get("device"))
        self.name_for("powerup", light.get("name"))

    def resource(self):
        snap = self.snapshot
        return snap.powerup_lights().get(self.rid) if snap else None

    def _reported(self):
        p = (self.resource() or {}).get("powerup")
        return p if p in POWERUP_PRESETS else None      # a custom power-up no preset expresses shows as unknown

    @property
    def current_option(self):
        return self.shown(self._reported())

    @callback
    def _handle_coordinator_update(self) -> None:
        self.pending_check(self._reported())
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_write("PUT", f"/bridges/{seg(self.bridge)}/light/{seg(self.rid)}/powerup", {"preset": option})
        self.pending_set(option)
