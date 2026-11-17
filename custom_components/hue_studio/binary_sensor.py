"""Whether hue-web answers: the one entity that stays available when it does not."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import HUB_DEVICE
from .entity import hub_device


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    rt = entry.runtime_data
    async_add_entities([HueWebOnline(rt.bridges, rt.api.base)])


class HueWebOnline(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "hue_web"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, base_url):
        super().__init__(coordinator)
        self._attr_unique_id = f"{HUB_DEVICE}_online"
        self._attr_device_info = hub_device(base_url)

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self):
        return {"bridges": sorted(self.coordinator.data or {})}
