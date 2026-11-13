# Hue Studio

A Home Assistant integration for what the core `hue` integration does not do: scene editing, scene history and restore,
gradients, power-up behaviour, room and zone membership, smart scene editing, motion sensor settings and the Zigbee
device search, as websocket commands.

Hue Studio is a thin client of a **hue-web** server (`/api/v1`). hue-web is the only process that talks to the Hue
bridges, so there is one connection per bridge, one traffic limiter and one scene history. Without a hue-web server this
integration does nothing.

## Install

1. HACS > Integrations > three dots > Custom repositories: add `https://github.com/jrx-code/hue-studio`, category
   Integration, then download Hue Studio.
2. Restart Home Assistant.
3. Settings > Devices & services > Add integration > Hue Studio, and enter the address of hue-web
   (for example `http://hue-web.local:8000`). The form checks `GET /healthz` before it saves.

hue-web has no login of its own on this port: allow only Home Assistant (and your reverse proxy) to reach it, for
example with a firewall rule on the host.

## Commands

| Command | Kind | hue-web route |
|---|---|---|
| `hue_studio/bridges` | read | `GET /bridges` |
| `hue_studio/state` | read | `GET /bridges/{b}/state?version=3` |
| `hue_studio/scene_get` | read | `GET /bridges/{b}/scene/{id}` |
| `hue_studio/scene_history` | read | `GET /bridges/{b}/scene/{id}/history` |
| `hue_studio/zigbee_status` | read | `GET /bridges/{b}/discover` |
| `hue_studio/scene_create` | write, admin, dry_run | `POST scene/from_current` or `scene/from_palette` |
| `hue_studio/scene_copy` | write, admin, dry_run | `POST scene/{id}/copy` |
| `hue_studio/scene_edit`, `scene_rename`, `scene_delete` | write, admin, dry_run | `PUT scene/{id}`, `PUT rename/scene/{id}`, `DELETE scene/{id}` |
| `hue_studio/light_gradient`, `powerup` | write, admin, dry_run | `PUT light/{id}/gradient`, `PUT light/{id}/powerup` |
| `hue_studio/set_lights` | write, admin, dry_run | `PUT room/{id}/lights`, `PUT zone/{id}/lights` |
| `hue_studio/device_room`, `light_zones` | write, admin, dry_run | `PUT device/{id}/room`, `PUT light/{id}/zones` |
| `hue_studio/smart_scene_action`, `smart_scene_edit` | write, admin, dry_run | `POST smart_scene/{id}/{action}`, `PUT smart_scene/{id}` |
| `hue_studio/motion_cfg` | write, admin, dry_run | `PUT motion/{id}` |
| `hue_studio/scene_restore` | write, admin | `POST scene/{id}/restore` |
| `hue_studio/zigbee_search` | write, admin | `POST discover` (serial numbers optional) |

Every command names its bridge as hue-web knows it. Write commands need an admin user. A write with `dry_run: true`
sends nothing to the bridge and answers the writes it would make: `{dry_run: true, writes: [{bridge, method, path, body}], result}`.

If hue-web is down the commands answer a `hue_error` ("hue-web unreachable"); the core `hue` integration keeps working.

## License

Apache License 2.0, see `LICENSE`.
