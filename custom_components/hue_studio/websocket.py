"""Websocket commands. Every command names its bridge (as hue-web knows it, e.g. `hue-bridge-main`).

The commands are a thin layer over the hue-web /api/v1 (the one process that owns the bridge connections, the traffic
limiter, the scene history and the automations). Reads are open to every user, writes need an admin. `dry_run` on a
write sends `X-Hue-Dry-Run` and returns the bridge calls hue-web would make: `{dry_run: true, writes: [...]}`; a real
write returns `{dry_run: false, result: ...}`.
"""
from __future__ import annotations

from urllib.parse import quote

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .api_client import ApiError, HueWebClient
from .const import DOMAIN

SMART_ACTIONS = ["activate", "deactivate"]
POWERUP_PRESETS = ["safety", "powerfail", "last_on_state"]
XY = [[vol.All(vol.Coerce(float), vol.Range(min=0, max=1))]]
# A resource id (UUID) or a bridge name (slug) is one path segment: no slash, no query, and never "." or ".." which a proxy
# would normalise into another route.
ID = vol.All(str, vol.Match(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}$"), vol.NotIn([".", ".."]))


def _client(hass: HomeAssistant) -> HueWebClient:
    clients = [v for v in hass.data.get(DOMAIN, {}).values() if isinstance(v, HueWebClient)]
    if not clients:
        raise ApiError("hue-web is not configured: add the Hue Studio integration", 404)
    return clients[0]


async def _run(hass: HomeAssistant, connection, msg, fn) -> None:
    try:
        result = await hass.async_add_executor_job(lambda: fn(_client(hass)))
    except ApiError as exc:
        connection.send_error(msg["id"], "hue_error", str(exc))
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        connection.send_error(msg["id"], "invalid_format", str(exc))
    else:
        connection.send_result(msg["id"], result)


@callback
def async_register(hass: HomeAssistant) -> None:
    for cmd in (ws_bridges, ws_scene_get, ws_scene_edit, ws_scene_rename, ws_scene_delete, ws_scene_history, ws_scene_restore,
                ws_zigbee_search, ws_zigbee_status, ws_state, ws_scene_create, ws_scene_copy,
                ws_light_gradient, ws_set_lights, ws_device_room, ws_light_zones,
                ws_smart_scene_action, ws_smart_scene_edit, ws_motion_cfg, ws_powerup):
        websocket_api.async_register_command(hass, cmd)


def q(value) -> str:
    """One path segment: every id is user input, so nothing may add a slash, dots or a query to the URL."""
    value = str(value)
    if value in ("", ".", ".."):
        raise ApiError("invalid id", 400)
    return quote(value, safe="")


def _b(msg) -> str:
    return "/bridges/" + q(msg["bridge"])


# -- reads -------------------------------------------------------------------
@websocket_api.websocket_command({vol.Required("type"): "hue_studio/bridges"})
@websocket_api.async_response
async def ws_bridges(hass, connection, msg) -> None:
    await _run(hass, connection, msg, lambda c: c.get("/bridges"))


@websocket_api.websocket_command({vol.Required("type"): "hue_studio/state", vol.Required("bridge"): ID})
@websocket_api.async_response
async def ws_state(hass, connection, msg) -> None:
    """Resource ids and capabilities of rooms, zones, lights, sensors and scenes."""
    await _run(hass, connection, msg, lambda c: c.get(_b(msg) + "/state", version=3))


@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/scene_get", vol.Required("bridge"): ID, vol.Required("scene_id"): ID,
})
@websocket_api.async_response
async def ws_scene_get(hass, connection, msg) -> None:
    await _run(hass, connection, msg, lambda c: c.get(f"{_b(msg)}/scene/{q(msg['scene_id'])}"))


@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/scene_history", vol.Required("bridge"): ID, vol.Required("scene_id"): ID,
})
@websocket_api.async_response
async def ws_scene_history(hass, connection, msg) -> None:
    """Earlier versions of a scene (newest first), kept by hue-web before every edit and restore."""
    await _run(hass, connection, msg, lambda c: c.get(f"{_b(msg)}/scene/{q(msg['scene_id'])}/history"))


@websocket_api.websocket_command({vol.Required("type"): "hue_studio/zigbee_status", vol.Required("bridge"): ID})
@websocket_api.async_response
async def ws_zigbee_status(hass, connection, msg) -> None:
    """Search status and the devices that joined since the last search started from hue-web."""
    await _run(hass, connection, msg, lambda c: c.get(_b(msg) + "/discover"))


# -- writes without a dry-run contract ---------------------------------------
@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/scene_restore", vol.Required("bridge"): ID, vol.Required("scene_id"): ID,
    vol.Required("index"): vol.All(int, vol.Range(min=0)),
})
@websocket_api.async_response
async def ws_scene_restore(hass, connection, msg) -> None:
    def run(c):
        c.request("POST", f"{_b(msg)}/scene/{q(msg['scene_id'])}/restore", {"index": msg["index"]})
        return {"restored": msg["index"]}
    await _run(hass, connection, msg, run)


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/zigbee_search", vol.Required("bridge"): ID,
    vol.Optional("codes", default=[]): [str], vol.Optional("allow_default_link_key", default=False): bool,
})
@websocket_api.async_response
async def ws_zigbee_search(hass, connection, msg) -> None:
    """Start the ~45 s search for new lights, remotes and sensors (serial numbers: 6 hex characters each)."""
    await _run(hass, connection, msg, lambda c: c.request(
        "POST", _b(msg) + "/discover", {"codes": msg["codes"], "allow_default_link_key": msg["allow_default_link_key"]}))


# -- writes with dry_run -----------------------------------------------------
async def _write(hass, connection, msg, method: str, path: str, body=None) -> None:
    await _run(hass, connection, msg, lambda c: c.write(method, path, body, dry_run=msg["dry_run"]))


def _dry():
    return {vol.Optional("dry_run", default=False): bool}


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/scene_edit", vol.Required("bridge"): ID, vol.Required("scene_id"): ID,
    vol.Required("edit"): dict, **_dry(),
})
@websocket_api.async_response
async def ws_scene_edit(hass, connection, msg) -> None:
    await _write(hass, connection, msg, "PUT", f"{_b(msg)}/scene/{q(msg['scene_id'])}", msg["edit"])


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/scene_rename", vol.Required("bridge"): ID, vol.Required("scene_id"): ID,
    vol.Required("name"): str, **_dry(),
})
@websocket_api.async_response
async def ws_scene_rename(hass, connection, msg) -> None:
    await _write(hass, connection, msg, "PUT", f"{_b(msg)}/rename/scene/{q(msg['scene_id'])}", {"name": msg["name"]})


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/scene_delete", vol.Required("bridge"): ID, vol.Required("scene_id"): ID, **_dry(),
})
@websocket_api.async_response
async def ws_scene_delete(hass, connection, msg) -> None:
    await _write(hass, connection, msg, "DELETE", f"{_b(msg)}/scene/{q(msg['scene_id'])}")


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/scene_create", vol.Required("bridge"): ID,
    vol.Required("target_group"): ID, vol.Required("name"): str, vol.Optional("palette"): XY, **_dry(),
})
@websocket_api.async_response
async def ws_scene_create(hass, connection, msg) -> None:
    if "palette" in msg:
        if any(len(p) != 2 for p in msg["palette"]):
            connection.send_error(msg["id"], "invalid_format", "palette points must be xy pairs")
            return
        await _write(hass, connection, msg, "POST", _b(msg) + "/scene/from_palette", {
            "target_group": msg["target_group"], "name": msg["name"], "image": "", "palette": msg["palette"]})
        return
    await _write(hass, connection, msg, "POST", _b(msg) + "/scene/from_current",
                 {"group": msg["target_group"], "name": msg["name"]})


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/scene_copy", vol.Required("bridge"): ID,
    vol.Required("scene_id"): ID, vol.Required("target_group"): ID, vol.Optional("name"): str, **_dry(),
})
@websocket_api.async_response
async def ws_scene_copy(hass, connection, msg) -> None:
    body = {"target_group": msg["target_group"], **({"name": msg["name"]} if msg.get("name") else {})}
    await _write(hass, connection, msg, "POST", f"{_b(msg)}/scene/{q(msg['scene_id'])}/copy", body)


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/light_gradient", vol.Required("bridge"): ID, vol.Required("light_id"): ID,
    vol.Required("points"): XY, vol.Optional("mode"): str, **_dry(),
})
@websocket_api.async_response
async def ws_light_gradient(hass, connection, msg) -> None:
    if any(len(p) != 2 for p in msg["points"]):
        connection.send_error(msg["id"], "invalid_format", "gradient points must be xy pairs")
        return
    await _write(hass, connection, msg, "PUT", f"{_b(msg)}/light/{q(msg['light_id'])}/gradient",
                 {"points": msg["points"], "mode": msg.get("mode")})


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/set_lights", vol.Required("bridge"): ID,
    vol.Required("group_type"): vol.In(["room", "zone"]), vol.Required("group_id"): ID,
    vol.Required("light_ids"): [str], **_dry(),
})
@websocket_api.async_response
async def ws_set_lights(hass, connection, msg) -> None:
    await _write(hass, connection, msg, "PUT", f"{_b(msg)}/{q(msg['group_type'])}/{q(msg['group_id'])}/lights",
                 {"lights": msg["light_ids"]})


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/device_room", vol.Required("bridge"): ID,
    vol.Required("device_id"): ID, vol.Required("room"): vol.Any(str, None), **_dry(),
})
@websocket_api.async_response
async def ws_device_room(hass, connection, msg) -> None:
    await _write(hass, connection, msg, "PUT", f"{_b(msg)}/device/{q(msg['device_id'])}/room", {"room": msg["room"]})


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/light_zones", vol.Required("bridge"): ID,
    vol.Required("light_id"): ID, vol.Required("zone_ids"): [str], **_dry(),
})
@websocket_api.async_response
async def ws_light_zones(hass, connection, msg) -> None:
    await _write(hass, connection, msg, "PUT", f"{_b(msg)}/light/{q(msg['light_id'])}/zones", {"lights": msg["zone_ids"]})


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/smart_scene_action", vol.Required("bridge"): ID,
    vol.Required("smart_scene_id"): ID, vol.Required("action"): vol.In(SMART_ACTIONS), **_dry(),
})
@websocket_api.async_response
async def ws_smart_scene_action(hass, connection, msg) -> None:
    await _write(hass, connection, msg, "POST", f"{_b(msg)}/smart_scene/{q(msg['smart_scene_id'])}/{q(msg['action'])}")


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/smart_scene_edit", vol.Required("bridge"): ID,
    vol.Required("smart_scene_id"): ID, vol.Required("edit"): dict, **_dry(),
})
@websocket_api.async_response
async def ws_smart_scene_edit(hass, connection, msg) -> None:
    await _write(hass, connection, msg, "PUT", f"{_b(msg)}/smart_scene/{q(msg['smart_scene_id'])}", msg["edit"])


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/motion_cfg", vol.Required("bridge"): ID,
    vol.Required("motion_id"): ID, vol.Optional("enabled"): bool,
    vol.Optional("sensitivity"): vol.All(int, vol.Range(min=0)), **_dry(),
})
@websocket_api.async_response
async def ws_motion_cfg(hass, connection, msg) -> None:
    body = {k: msg[k] for k in ("enabled", "sensitivity") if k in msg}
    await _write(hass, connection, msg, "PUT", f"{_b(msg)}/motion/{q(msg['motion_id'])}", body)


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): "hue_studio/powerup", vol.Required("bridge"): ID,
    vol.Required("light_id"): ID, vol.Required("preset"): vol.In(POWERUP_PRESETS), **_dry(),
})
@websocket_api.async_response
async def ws_powerup(hass, connection, msg) -> None:
    await _write(hass, connection, msg, "PUT", f"{_b(msg)}/light/{q(msg['light_id'])}/powerup", {"preset": msg["preset"]})
