"""JI-hub scenes: kept by hue-web, spanning rooms and both bridges, recalled light by light. Core hue cannot see them."""
from __future__ import annotations

import logging

from homeassistant.components.scene import Scene
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import HUB_DEVICE
from .coordinator import seg
from .entity import add_new, hub_device

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    rt = entry.runtime_data
    add_new(entry, rt.hub, async_add_entities,
            lambda: [HubScene(rt.hub, rt.bridges, rt.api.base, sid) for sid in (rt.hub.data or {})])


class HubScene(CoordinatorEntity, Scene):
    _attr_has_entity_name = True
    _attr_icon = "mdi:palette-swatch-variant"

    def __init__(self, coordinator, bridges, base_url, sid):
        super().__init__(coordinator)
        self.sid, self.bridges = sid, bridges
        self._attr_unique_id = f"{HUB_DEVICE}_scene_{sid}"
        self._attr_device_info = hub_device(base_url)

    def _scene(self) -> dict | None:
        return (self.coordinator.data or {}).get(self.sid)

    @property
    def name(self):
        return (self._scene() or {}).get("name") or self.sid

    @property
    def available(self) -> bool:
        return super().available and self._scene() is not None

    @property
    def extra_state_attributes(self):
        s = self._scene() or {}
        return {"hub_scene_id": self.sid, "lights": s.get("lights"), "lights_on": s.get("lights_on"),
                "bridges": s.get("bridges"), "updated": s.get("updated")}

    async def async_activate(self, **kwargs) -> None:
        out = await self.coordinator.async_write("POST", f"/hub-scenes/{seg(self.sid)}/recall")
        res = out.get("result") or {}
        errors = res.get("errors") or []
        await self.bridges.async_request_refresh()
        if errors and not res.get("sent"):
            raise HomeAssistantError(f"Hue Studio: {self.name}: " + "; ".join(errors[:3]))
        if errors:
            _LOGGER.warning("%s: %d light(s) refused: %s", self.name, len(errors), "; ".join(errors[:5]))
