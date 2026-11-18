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

Entities about a light, sensor, room or zone are attached to the device the core `hue` integration already made for it.

| Entity | Where | What it shows or sets |
|---|---|---|
| `switch` &lt;smart scene&gt; schedule | room or zone | the smart scene (schedule) runs; off stops it (core hue can only start it) |
| `switch` Dynamic scene | room or zone | the active scene plays its colour palette; on plays it, off holds the colours |
| `number` Dynamic speed | room or zone | palette speed of the active scene, 1 to 100 % |
| `number` Motion sensitivity | motion sensor | sensitivity of the sensor |
| `select` Power-on behaviour | light | after a power cut: safety, restore, last state (disabled by default) |
| `update` Bridge and device software | bridge | devices ready to install; Install runs the bridge's install of everything ready (the bridge has no per-device install) and restarts the bridge for 2 to 3 minutes |
| `sensor` Scenes in bridge memory, Scene memory used | bridge | scenes stored and the share of the bridge limit in use |
| `sensor` Scenes without references | bridge | scenes no smart scene, sensor or switch rule, hue-web reaction, Home Assistant automation or script recalls |
| `scene` per hub scene | Hue Web | a hue-web scene that spans bridges; activating it recalls it on every bridge |
| `binary_sensor` Reachable | Hue Web | hue-web answers |

Dynamic scene and speed exist for rooms and zones with at least one scene that has a palette; those of zones start
disabled (zones overlap the rooms).

hue-web relays the bridge event stream, so a change made in the Hue app shows within seconds (an event re-reads only its own bridge); while both streams are up
the integration polls every 5 minutes, otherwise every minute. Scene usage, sensor and switch rules and software state
are read every 5 minutes and after a change. Entities of resources removed from a bridge leave the registry after two
reads without them.

## Services

Targets are names (case and Polish diacritics ignored), `bridge:name` when two bridges share a name, a resource id, or
an entity of the core `hue` integration. Every service takes `dry_run: true` and then answers the writes it would make
without sending any. With `return_response` each one answers what it did. Services that change stored scenes need an
admin user (automations and scripts may call them).

| Service | Does |
|---|---|
| `hue_studio.create_hub_scene` | a hub scene from the current state of rooms or zones, on one or several bridges |
| `hue_studio.snapshot_scene` | a bridge scene from the current state of a room or zone |
| `hue_studio.copy_scene` | a bridge scene copied to another room or zone |
| `hue_studio.restore_scene` | an earlier version of a bridge scene from the hue-web history (1 = before the last edit) |
| `hue_studio.delete_scenes` | deletes bridge scenes to free memory; a used scene is skipped with the reason; dry run unless `dry_run: false` |
| `hue_studio.set_effect` | an effect on a room, zone or light (`candle`, `fire`, ... on the light; `breathe`, `wave`, `random` run by hue-web for N minutes); `no_effect` stops both |
| `hue_studio.timed_effect` | `sunrise` or `sunset` over N minutes |

`delete_scenes` does not see dashboards or the Hue app's own scene list: review the candidates before deleting.

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
