"""Which bridge scenes Home Assistant itself uses: automations and scripts that name core hue's scene entity."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CORE_HUE


def ha_scene_refs(hass: HomeAssistant, scene_ids) -> dict[str, list[str]]:
    """scene rid -> automation/script entity ids that reference core hue's scene entity of it."""
    from homeassistant.components.automation import automations_with_entity
    from homeassistant.components.script import scripts_with_entity

    reg = er.async_get(hass)
    out: dict[str, list[str]] = {}
    for sid in scene_ids:
        entity_id = reg.async_get_entity_id("scene", CORE_HUE, sid)
        if not entity_id:
            continue
        users = []
        if "automation" in hass.config.components:
            users += automations_with_entity(hass, entity_id)
        if "script" in hass.config.components:
            users += scripts_with_entity(hass, entity_id)
        if users:
            out[sid] = sorted(users)
    return out
