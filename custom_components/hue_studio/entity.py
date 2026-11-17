"""The base of every Hue Studio entity and the device it belongs to.

An entity about one bridge resource lands on the device the core `hue` integration made for it, when that exists
((hue, device rid), the bridge as (hue, bridge_id)): its settings then sit on the same device page as its light or sensor.
Without core `hue` (a test instance) they land on a Hue Studio bridge device. Hub scenes and reachability belong to the
Hue Web service device.
"""
from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CORE_HUE, DOMAIN, HUB_DEVICE
from .model import Snapshot


def bridge_key(snap: Snapshot) -> str:
    """The stable part of a bridge's unique ids: its bridge_id (hex), the name only if hue-web gave none."""
    return str(snap.info.get("bridge_id") or snap.name).lower()


def hub_device(base_url: str) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, HUB_DEVICE)}, name="Hue Web", manufacturer="JI ENGINEERING", model="hue-web",
                      entry_type=DeviceEntryType.SERVICE, configuration_url=base_url)


def core_device(hass, rid: str | None):
    """The device core `hue` made for this resource (light or sensor device rid, or the bridge_id), if any.

    Since HA 2026.10 device identifiers are no longer unique across config entries, so the device is picked by the owning
    config entry (domain `hue`), and the entity attaches through `device_entry` instead of a DeviceInfo with hue's
    identifier (that would create a second device for this entry).
    """
    if not rid:
        return None
    reg = dr.async_get(hass)
    ident = (CORE_HUE, str(rid))
    found = reg.async_get_devices(identifiers={ident}) if hasattr(reg, "async_get_devices") else \
        [d for d in [reg.async_get_device(identifiers={ident})] if d]
    for d in found:
        if any((e := hass.config_entries.async_get_entry(ce)) and e.domain == CORE_HUE for ce in d.config_entries):
            return d
    return None


def bridge_device(snap: Snapshot) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, bridge_key(snap))}, name=f"Hue Studio {snap.name}",
                      manufacturer="Signify (through hue-web)", model=snap.info.get("model"), sw_version=snap.info.get("sw"))


class StudioEntity(CoordinatorEntity):
    """An entity of one resource of one bridge; unavailable while the resource is missing from hue-web."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, snap: Snapshot, kind: str, rid: str, device_rid: str | None = None) -> None:
        super().__init__(coordinator)
        self.bridge, self.rid = snap.name, rid
        self._attr_unique_id = f"{bridge_key(snap)}_{kind}_{rid}"
        hass = coordinator.hass
        own = core_device(hass, device_rid)
        dev = own or core_device(hass, str(snap.info.get("bridge_id") or "").lower() or None)
        if dev is not None:
            self.device_entry = dev                 # core hue's device (HA attaches through device_entry when no DeviceInfo)
            self._attr_device_info = None
        else:
            self._attr_device_info = bridge_device(snap)
        # On the light or sensor's own device the name is just the setting; elsewhere it needs the resource name too.
        self.on_own_device = own is not None

    def name_for(self, key: str, resource_name: str | None) -> None:
        """Translation key `key` on the resource's own device, `key_of` with the {name} placeholder elsewhere."""
        if self.on_own_device:
            self._attr_translation_key = key
        else:
            self._attr_translation_key = f"{key}_of"
            self._attr_translation_placeholders = {"name": resource_name or self.rid}

    @property
    def snapshot(self) -> Snapshot | None:
        return (self.coordinator.data or {}).get(self.bridge)

    def resource(self) -> dict | None:
        raise NotImplementedError

    @property
    def available(self) -> bool:
        return super().available and self.resource() is not None


def add_new(entry, coordinator, async_add_entities, build) -> None:
    """Add what `build()` returns now and, after each refresh, entities of resources that appeared since."""
    known: set[str] = set()

    def _sync() -> None:
        fresh = [e for e in build() if e.unique_id not in known]
        known.update(e.unique_id for e in fresh)
        if fresh:
            async_add_entities(fresh)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class Optimistic:
    """A setting written through hue-web shows the new value at once, until the bridge reports it or two refreshes pass."""

    _pending = None
    _waited = 0

    def pending_set(self, value) -> None:
        self._pending, self._waited = value, 0
        self.async_write_ha_state()

    def pending_check(self, reported) -> None:
        if self._pending is not None:
            self._waited += 1
            if reported == self._pending or self._waited >= 2:
                self._pending = None

    def shown(self, reported):
        return self._pending if self._pending is not None else reported
