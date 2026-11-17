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

    def scene_usage(self) -> tuple[int | None, int | None]:
        cap = self.capacity or {}
        return cap.get("scenes"), cap.get("max_scenes")


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
STRUCTURE_TYPES = {"scene", "smart_scene", "light", "device", "room", "zone", "motion", "grouped_light"}


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
    return False
