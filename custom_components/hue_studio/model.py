"""What the entities read from hue-web, free of Home Assistant types so it can be tested against the real hue-web app.

One `Snapshot` per bridge: the `/state?version=3` answer and the `/capacity` answer, plus the hub scenes (one list for the
whole hue-web, spanning both bridges). Every accessor returns plain dicts keyed by the bridge resource id (rid), which is
also the stable part of every unique_id.
"""
from __future__ import annotations

from dataclasses import dataclass, field

POWERUP_PRESETS = ["safety", "powerfail", "last_on_state"]


@dataclass
class Snapshot:
    """One bridge as hue-web reports it."""

    name: str
    state: dict = field(default_factory=dict)
    capacity: dict | None = None
    updates: dict | None = None        # GET /updates?notes=false: the bridge and every device's software state
    usage: dict | None = None          # GET /usage?version=3: scene id -> what recalls it (smart scenes, reactions)
    rules: dict | None = None          # GET /bridge-rules: native rules of sensors and switches, scenes they recall

    @property
    def info(self) -> dict:
        return self.state.get("bridge") or {}

    def smart_scenes(self) -> dict[str, dict]:
        return {s["id"]: s for s in self.state.get("smart_scenes") or [] if s.get("id")}

    def motion_sensors(self) -> dict[str, dict]:
        """Sensors with a motion service, keyed by that service's rid (the one `PUT /motion/{rid}` takes)."""
        return {s["motion_id"]: s for s in self.state.get("sensors") or [] if s.get("motion_id")}

    def lights(self) -> dict[str, dict]:
        return {x["id"]: x for x in self.state.get("lights") or [] if x.get("id")}

    def powerup_lights(self) -> dict[str, dict]:
        return {rid: x for rid, x in self.lights().items() if x.get("supports_powerup")}

    def area_names(self) -> dict[str, str]:
        """rid -> name of every room and zone (the `group_names` map of the state, rooms and zones as a fallback)."""
        names = {k: v for k, v in (self.state.get("group_names") or {}).items() if isinstance(v, str)}
        for kind in ("rooms", "zones"):
            for g in self.state.get(kind) or []:
                if g.get("id") and g.get("name"):
                    names.setdefault(g["id"], g["name"])
        return names

    def areas(self) -> dict[str, dict]:
        """Rooms and zones: rid -> {name, kind, lights (count), effects (union of the lights' effects)}."""
        out = {}
        for kind in ("rooms", "zones"):
            for g in self.state.get(kind) or []:
                if not g.get("id"):
                    continue
                effects: list[str] = []
                for light in g.get("lights") or []:
                    for e in light.get("effects") or []:
                        if e not in effects:
                            effects.append(e)
                out[g["id"]] = {"name": g.get("name") or g["id"], "kind": "zone" if kind == "zones" else "room",
                                "lights": len(g.get("lights") or []), "effects": effects}
        return out

    def area_lights(self, rid: str) -> list[str]:
        for kind in ("rooms", "zones"):
            for g in self.state.get(kind) or []:
                if g.get("id") == rid:
                    return [x["id"] for x in g.get("lights") or [] if x.get("id")]
        return []

    def dynamic_areas(self) -> dict[str, dict]:
        """Rooms and zones with at least one scene that can play its palette: rid -> {name, kind}."""
        groups = {s.get("group") for s in self.state.get("scenes") or [] if s.get("palette")}
        return {rid: a for rid, a in self.areas().items() if rid in groups}

    def active_scene(self, area: str) -> dict | None:
        """The scene the bridge reports active in a room or zone (the playing one first), if any."""
        rows = [s for s in self.state.get("scenes") or [] if s.get("group") == area and s.get("active")]
        rows.sort(key=lambda s: not s.get("playing"))
        return rows[0] if rows else None

    def scene_usage(self) -> tuple[int | None, int | None]:
        cap = self.capacity or {}
        return cap.get("scenes"), cap.get("max_scenes")


def firmware(updates: dict | None) -> dict | None:
    """The bridge's software state for an update entity: version, devices ready and pending, installing."""
    if not updates:
        return None
    b = updates.get("bridge") or {}
    devices = updates.get("devices") or []
    ready = [d for d in devices if d.get("state") == "ready_to_install"]
    pending = [d for d in devices if d.get("state") == "update_pending"]
    return {"version": b.get("swversion"), "bridge_ready": b.get("state") == "readytoinstall",
            "install_available": bool(b.get("install_available")),
            "installing": bool((updates.get("counts") or {}).get("installing")) or b.get("state") == "installing",
            "ready": ready, "pending": pending, "autoinstall": (b.get("autoinstall") or {}).get("on"),
            "autoinstall_time": _clock((b.get("autoinstall") or {}).get("updatetime"))}


def _clock(value) -> str | None:
    """The bridge's "T03:00:00" as "03:00"."""
    text = str(value or "").lstrip("T")
    return text[:5] if len(text) >= 5 and text[2] == ":" else None


def scene_refs(snap: "Snapshot") -> dict[str, list[str]] | None:
    """scene id -> what on the bridge side recalls it (smart scenes, hue-web reactions, native sensor/switch rules).

    None while either source is unknown: a scene is never called unreferenced on a partial picture.
    """
    if snap.usage is None or snap.rules is None:
        return None
    out: dict[str, list[str]] = {}
    for sid, rows in ((snap.usage or {}).get("scenes") or {}).items():
        for row in rows or []:
            out.setdefault(sid, []).append(f"{row.get('kind', 'smart_scene')}: {row.get('name') or row.get('id')}")
    names = {r["id"]: r.get("name") for r in (snap.rules or {}).get("rules") or []}
    for sid, rule_ids in ((snap.rules or {}).get("scenes") or {}).items():
        for rid in rule_ids:
            out.setdefault(sid, []).append(f"bridge rule: {names.get(rid) or rid}")
    return out


def scene_label(snap: "Snapshot", scene: dict) -> str:
    area = snap.area_names().get(scene.get("group")) or ""
    return f"{scene.get('name') or scene.get('id')}@{area}" if area else str(scene.get("name") or scene.get("id"))


def capacity_percent(used: int | None, limit: int | None) -> float | None:
    if not isinstance(used, int) or not isinstance(limit, int) or limit <= 0:
        return None
    return round(100.0 * used / limit, 1)


def hub_scenes(answer: dict | None) -> dict[str, dict]:
    """GET /hub-scenes answers {scenes: [summary...]}; keyed by the scene id hue-web gave it."""
    return {s["id"]: s for s in (answer or {}).get("scenes") or [] if s.get("id")}


def smart_scene_active(s: dict) -> bool:
    return s.get("active") is True or s.get("state") == "active"


# -- targets of the services --------------------------------------------------------------------------------------------
HUB_EFFECTS = ["breathe", "wave", "random"]          # run by hue-web, minutes 1..720
TIMED_EFFECTS = ["sunrise", "sunset", "no_effect"]   # run by the light, minutes 1..60


class TargetError(ValueError):
    """A name or id that matches nothing, or more than one thing; the message lists what was found."""


def _norm(text: str) -> str:
    import unicodedata
    t = str(text).replace("ł", "l").replace("Ł", "L")      # NFKD has no decomposition for ł
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().casefold()
    return " ".join(t.split())


@dataclass
class Target:
    kind: str            # "area" (room or zone) or "light"
    bridge: str
    rid: str             # room/zone rid, or light rid
    name: str
    grouped_light: str | None = None


def _targets(snaps: dict[str, Snapshot]) -> list[Target]:
    out = []
    for snap in snaps.values():
        for kind in ("rooms", "zones"):
            for g in snap.state.get(kind) or []:
                if g.get("id"):
                    out.append(Target("area", snap.name, g["id"], g.get("name") or g["id"], g.get("grouped_light")))
        for light in snap.state.get("lights") or []:
            if light.get("id"):
                out.append(Target("light", snap.name, light["id"], light.get("name") or light["id"]))
    return out


def resolve(snaps: dict[str, Snapshot], text: str, kinds: tuple[str, ...] = ("area", "light")) -> Target:
    """A room, zone or light by rid, grouped_light rid (what core hue's room light entity carries) or name.

    `bridge:name` limits the search to one bridge. Names compare without case and Polish diacritics.
    """
    text = str(text or "").strip()
    if not text:
        raise TargetError("empty target")
    bridge = None
    if ":" in text and text.split(":", 1)[0] in snaps:
        bridge, text = text.split(":", 1)
    pool = [t for t in _targets(snaps) if t.kind in kinds and (bridge is None or t.bridge == bridge)]
    exact = [t for t in pool if text in (t.rid, t.grouped_light)]
    if exact:
        return exact[0]
    want = _norm(text)
    found = [t for t in pool if _norm(t.name) == want]
    if len(found) == 1:
        return found[0]
    if not found:
        raise TargetError(f"no {' or '.join(kinds)} named '{text}'")
    raise TargetError(f"'{text}' is ambiguous: " + ", ".join(f"{t.bridge}:{t.name} ({t.kind})" for t in found[:6])
                      + "; prefix the bridge (bridge:name)")


def resolve_scene(snaps: dict[str, Snapshot], text: str) -> tuple[str, dict]:
    """A bridge scene by rid or by name (`bridge:name`, or `name@area` when several areas have a scene of that name)."""
    text = str(text or "").strip()
    bridge = None
    if ":" in text and text.split(":", 1)[0] in snaps:
        bridge, text = text.split(":", 1)
    area = None
    if "@" in text:
        text, area = (p.strip() for p in text.rsplit("@", 1))
    rows = []
    for snap in snaps.values():
        if bridge and snap.name != bridge:
            continue
        names = snap.area_names()
        for s in snap.state.get("scenes") or []:
            rows.append((snap.name, s, names.get(s.get("group")) or ""))
    exact = [(b, s) for b, s, _ in rows if s.get("id") == text]
    if exact:
        return exact[0]
    found = [(b, s, a) for b, s, a in rows if _norm(s.get("name") or "") == _norm(text) and (area is None or _norm(a) == _norm(area))]
    if len(found) == 1:
        return found[0][0], found[0][1]
    if not found:
        raise TargetError(f"no scene named '{text}'")
    raise TargetError(f"scene '{text}' is in several areas: " + ", ".join(f"{b}:{s['name']}@{a}" for b, s, a in found[:6]))


# -- the bridge event stream (SSE relay of CLIP v2 events) ---------------------------------------------------------------
STRUCTURE_TYPES = {"scene", "smart_scene", "light", "device", "room", "zone", "motion", "grouped_light", "behavior_instance"}


def needs_refresh(frame: list) -> bool:
    """Whether a CLIP v2 event frame changes what the entities show.

    A motion sensor reports every few seconds and a full state is ~550 kB, so only configuration matters: resources
    added or removed, a smart scene starting or stopping, a motion sensor's enabled/sensitivity, a light's power-up.
    """
    for event in frame if isinstance(frame, list) else []:
        kind = event.get("type")
        for row in event.get("data") or []:
            rtype = row.get("type")
            if kind in ("add", "delete") and rtype in STRUCTURE_TYPES:
                return True
            if kind != "update":
                continue
            if rtype == "smart_scene":
                return True
            if rtype == "motion" and ("enabled" in row or "sensitivity" in row):
                return True
            if rtype == "light" and "powerup" in row:
                return True
            if rtype == "behavior_instance" and "enabled" in row:      # a sensor or switch rule on/off
                return True
            if rtype in ("device_software_update", "bridge"):           # firmware state of a device or the bridge
                return True
            # A scene that starts playing its palette, or a new speed. Other recalls (status static/active) are frequent and
            # change no entity: a dynamics switch shows its own writes at once and other changes at the next poll.
            if rtype == "scene" and ("speed" in row or (row.get("status") or {}).get("active") == "dynamic_palette"):
                return True
    return False


SMART_STATE_KEYS = {"id", "id_v1", "owner", "type", "state", "active_timeslot"}


def smart_scene_states(frame: list) -> dict[str, str] | None:
    """{smart scene rid: "active"/"inactive"} when the only reason a frame would refresh is smart scenes starting or
    stopping, else None. Those are most refreshes (10 of 10 in 13 min on 2026-11-18) and the event carries the new state,
    so the entities update from it without reading the bridge (#218)."""
    out: dict[str, str] = {}
    for event in frame if isinstance(frame, list) else []:
        for row in event.get("data") or []:
            if not needs_refresh([{"type": event.get("type"), "data": [row]}]):
                continue
            if (event.get("type") == "update" and row.get("type") == "smart_scene" and row.get("id")
                    and row.get("state") in ("active", "inactive") and set(row) <= SMART_STATE_KEYS):
                out[row["id"]] = row["state"]
            else:
                return None
    return out or None


SLOW_TYPES = {"behavior_instance", "device_software_update", "bridge", "scene", "smart_scene"}


def needs_slow_reads(frame: list) -> bool:
    """Whether a frame changes what the slow reads hold: rules, firmware, or which scenes exist and recall what.

    A scene recall (status update) is not one: it changes the state only, and recalls are frequent.
    """
    for event in frame if isinstance(frame, list) else []:
        kind = event.get("type")
        for row in event.get("data") or []:
            rtype = row.get("type")
            if rtype not in SLOW_TYPES:
                continue
            if kind in ("add", "delete") or rtype in ("behavior_instance", "device_software_update", "bridge"):
                return True
            if rtype == "smart_scene" and "week_timeslots" in row:
                return True
    return False

