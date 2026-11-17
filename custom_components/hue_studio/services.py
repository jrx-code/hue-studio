"""Services for automations: what no Hue Studio entity does. Targets by Hue name, rid, or a core hue entity.

Every service takes `dry_run` (hue-web plans the bridge calls and sends nothing) and returns its result when the caller
asks for a response. Power-up, sensitivity and smart scenes have entities instead of services.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import CORE_HUE, DOMAIN
from .coordinator import seg
from .model import HUB_EFFECTS, TIMED_EFFECTS, TargetError, resolve, resolve_scene

DRY = {vol.Optional("dry_run", default=False): cv.boolean}


def _runtime(hass: HomeAssistant):
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if getattr(e, "runtime_data", None) is not None]
    if not entries:
        raise ServiceValidationError("Hue Studio is not set up (or hue-web is not reachable yet)")
    return entries[0].runtime_data


def _hue_rid(hass: HomeAssistant, text: str) -> str:
    """A core hue entity (light.*, scene.*) becomes the resource rid it carries as unique_id; anything else is kept."""
    if "." in text and text.split(".", 1)[0] in ("light", "scene"):
        ent = er.async_get(hass).async_get(text)
        if ent is None:
            raise ServiceValidationError(f"unknown entity {text}")
        if ent.platform != CORE_HUE:
            raise ServiceValidationError(f"{text} is not an entity of the Hue integration")
        return ent.unique_id
    return text


def _target(hass, rt, text, kinds=("area", "light")):
    try:
        return resolve(rt.bridges.data or {}, _hue_rid(hass, text), kinds)
    except TargetError as exc:
        raise ServiceValidationError(str(exc)) from exc


async def _create_hub_scene(call: ServiceCall):
    hass, rt = call.hass, _runtime(call.hass)
    targets = []
    for text in call.data["areas"]:
        t = _target(hass, rt, text, ("area",))
        targets.append({"bridge": t.bridge, "group": t.rid})
    body = {"name": call.data["name"], "targets": targets}
    if call.data["dry_run"]:      # nothing reaches a bridge either way; hue-web has no dry run for this file write
        return {"dry_run": True, "writes": [], "would_create": body}
    return await rt.hub.async_write("POST", "/hub-scenes/from_current", body)


async def _snapshot_scene(call: ServiceCall):
    hass, rt = call.hass, _runtime(call.hass)
    t = _target(hass, rt, call.data["area"], ("area",))
    return await rt.bridges.async_write("POST", f"/bridges/{seg(t.bridge)}/scene/from_current",
                                        {"group": t.rid, "name": call.data["name"]}, dry_run=call.data["dry_run"])


async def _copy_scene(call: ServiceCall):
    hass, rt = call.hass, _runtime(call.hass)
    try:
        bridge, scene = resolve_scene(rt.bridges.data or {}, _hue_rid(hass, call.data["scene"]))
    except TargetError as exc:
        raise ServiceValidationError(str(exc)) from exc
    t = _target(hass, rt, call.data["target"], ("area",))
    if t.bridge != bridge:
        raise ServiceValidationError(f"the scene is on {bridge}, the target area on {t.bridge}: a copy stays on one bridge")
    body = {"target_group": t.rid, **({"name": call.data["name"]} if call.data.get("name") else {})}
    return await rt.bridges.async_write("POST", f"/bridges/{seg(bridge)}/scene/{seg(scene['id'])}/copy", body,
                                        dry_run=call.data["dry_run"])


async def _set_effect(call: ServiceCall):
    hass, rt = call.hass, _runtime(call.hass)
    t = _target(hass, rt, call.data["target"])
    effect, dry = call.data["effect"], call.data["dry_run"]
    b = seg(t.bridge)
    if effect in HUB_EFFECTS:
        target = t.rid if t.kind == "light" else t.grouped_light
        if not target:
            raise ServiceValidationError(f"{t.name} has no grouped light for a hub effect")
        body = {"target": target, "target_type": "light" if t.kind == "light" else "area", "effect": effect,
                "minutes": call.data.get("minutes", 10), **({"speed": call.data["speed"]} if "speed" in call.data else {})}
        if dry:      # hue-web has no dry run for its own effects (#194): plan here, send nothing
            return {"dry_run": True, "writes": [], "would_start": {"bridge": t.bridge, **body}}
        return await rt.bridges.async_write("POST", f"/bridges/{b}/hub-effect", body)
    body = {"effect": effect, **({"speed": call.data["speed"]} if "speed" in call.data else {})}
    path = f"/bridges/{b}/{'light' if t.kind == 'light' else 'area'}/{seg(t.rid)}/effect"
    out = await rt.bridges.async_write("PUT", path, body, dry_run=dry)
    if effect == "no_effect" and not dry:      # also stop what hue-web runs on the lights of this target
        lights = {t.rid} if t.kind == "light" else set((rt.bridges.data or {})[t.bridge].area_lights(t.rid))
        running = (await rt.api.get(f"/bridges/{b}/hub-effects")).get("running") or []
        for run in running:
            if lights & set(run.get("lights") or []):
                await rt.bridges.async_write("DELETE", f"/bridges/{b}/hub-effect/{seg(run['id'])}")
    return out


async def _timed_effect(call: ServiceCall):
    hass, rt = call.hass, _runtime(call.hass)
    t = _target(hass, rt, call.data["target"])
    body = {"effect": call.data["effect"], **({"minutes": call.data["minutes"]} if "minutes" in call.data else {})}
    path = f"/bridges/{seg(t.bridge)}/{'light' if t.kind == 'light' else 'area'}/{seg(t.rid)}/timed_effect"
    return await rt.bridges.async_write("PUT", path, body, dry_run=call.data["dry_run"])


SERVICES = {
    "create_hub_scene": (_create_hub_scene, vol.Schema({vol.Required("name"): cv.string,
                                                        vol.Required("areas"): vol.All(cv.ensure_list, [cv.string], vol.Length(min=1)), **DRY})),
    "snapshot_scene": (_snapshot_scene, vol.Schema({vol.Required("area"): cv.string, vol.Required("name"): cv.string, **DRY})),
    "copy_scene": (_copy_scene, vol.Schema({vol.Required("scene"): cv.string, vol.Required("target"): cv.string,
                                            vol.Optional("name"): cv.string, **DRY})),
    "set_effect": (_set_effect, vol.Schema({vol.Required("target"): cv.string, vol.Required("effect"): cv.string,
                                            vol.Optional("minutes"): vol.All(vol.Coerce(float), vol.Range(min=1, max=720)),
                                            vol.Optional("speed"): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)), **DRY})),
    "timed_effect": (_timed_effect, vol.Schema({vol.Required("target"): cv.string, vol.Required("effect"): vol.In(TIMED_EFFECTS),
                                                vol.Optional("minutes"): vol.All(vol.Coerce(float), vol.Range(min=1, max=60)), **DRY})),
}


def async_register(hass: HomeAssistant) -> None:
    for name, (handler, schema) in SERVICES.items():
        hass.services.async_register(DOMAIN, name, handler, schema=schema, supports_response=SupportsResponse.OPTIONAL)
