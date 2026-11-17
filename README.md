# Hue Studio

A Home Assistant integration for what the core `hue` integration does not do: scene memory per bridge, smart scene
schedules, motion sensor sensitivity, power-up behaviour, scenes that span several bridges, scene snapshots and copies,
effects with a timer, plus scene editing, history and restore as websocket commands.

Hue Studio is a thin client of a **hue-web** server (`/api/v1`). hue-web is the only process that talks to the Hue
bridges, so there is one connection per bridge, one traffic limiter and one scene history. Without a hue-web server this
integration does nothing.

## Install

1. Add the custom repository `https://github.com/jrx-code/hue-studio`, category Integration, and download Hue Studio
   (Settings > Marketplace from Home Assistant 2026.11, HACS on older versions).
2. Restart Home Assistant.
3. Settings > Devices & services > Add integration > Hue Studio, and enter the address of hue-web
   (for example `http://hue-web.local:8000`). The form checks `GET /healthz` before it saves.

hue-web has no login of its own on this port: allow only Home Assistant (and your reverse proxy) to reach it, for
example with a firewall rule on the host.

Settings > Devices & services > Hue Studio > Reconfigure changes the address later.

## Entities

Entities of a sensor or a light are attached to the device the core `hue` integration already made for it.

| Entity | What it shows or sets |
|---|---|
| `binary_sensor` Reachable | hue-web answers |
| `sensor` Scenes, Scene memory | scenes stored on each bridge, and the share of the bridge limit in use |
| `switch` per smart scene | the smart scene (schedule) is running; on and off start and stop it |
| `number` Motion sensitivity | sensitivity of each motion sensor |
| `select` Power-up | power-up behaviour of each light (disabled by default) |
| `scene` per hub scene | a hue-web scene that spans bridges; activating it recalls it on every bridge |

hue-web relays the bridge event stream, so a change made in the Hue app shows within seconds; while both streams are up
the integration polls every 5 minutes, otherwise every minute. Entities of resources removed from a bridge leave the
registry after two reads without them.

## Services

Targets are names (case and Polish diacritics ignored), `bridge:name` when two bridges share a name, a resource id, or
an entity of the core `hue` integration. Every service takes `dry_run: true` and then answers the writes it would make
without sending any. With `return_response` each one answers what it did.

| Service | Does |
|---|---|
| `hue_studio.create_hub_scene` | a hub scene from the current state of rooms or zones, on one or several bridges |
| `hue_studio.snapshot_scene` | a bridge scene from the current state of a room or zone |
| `hue_studio.copy_scene` | a bridge scene copied to another room or zone |
| `hue_studio.set_effect` | an effect on a room, zone or light (`candle`, `fire`, ... on the light; `breathe`, `wave`, `random` run by hue-web for N minutes); `no_effect` stops both |
| `hue_studio.timed_effect` | `sunrise` or `sunset` over N minutes |

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
