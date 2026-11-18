"""Software of each bridge and its devices as one update entity on the bridge device.

The bridge installs everything it holds ready in one go (itself and every ready device; there is no per-device install),
so one entity per bridge is the honest shape: "latest" differs from "installed" while anything is ready, the summary
names what, and Install sends the bridge's own install command through hue-web.
"""
from __future__ import annotations

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.const import EntityCategory

from .coordinator import seg
from .entity import StudioEntity, add_new
from .model import firmware

SUMMARY_MAX = 255


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.bridges

    def build():
        return [BridgeFirmware(coordinator, snap) for snap in (coordinator.data or {}).values() if snap.updates]
    add_new(entry, coordinator, async_add_entities, build)


class BridgeFirmware(StudioEntity, UpdateEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_features = UpdateEntityFeature.INSTALL
    _attr_translation_key = "firmware"
    _attr_title = "Philips Hue"

    def __init__(self, coordinator, snap):
        super().__init__(coordinator, snap, "firmware", "bridge")

    def resource(self):
        snap = self.snapshot
        return firmware(snap.updates) if snap else None

    @property
    def installed_version(self):
        return (self.resource() or {}).get("version")

    @property
    def latest_version(self):
        fw = self.resource() or {}
        n = len(fw.get("ready") or []) + (1 if fw.get("bridge_ready") else 0)
        if not fw.get("install_available") or not n:
            return fw.get("version")
        return f"{fw.get('version')} + {n} ready"

    @property
    def in_progress(self):
        return bool((self.resource() or {}).get("installing"))

    @property
    def release_summary(self):
        fw = self.resource() or {}
        parts = []
        if fw.get("bridge_ready"):
            parts.append("bridge")
        parts += [d.get("name") or d.get("id") for d in fw.get("ready") or []]
        text = "Ready: " + ", ".join(parts) if parts else ""
        if fw.get("pending"):
            text += ("; " if text else "") + f"downloading: {len(fw['pending'])}"
        if not text:
            return None
        # Installing restarts the bridge: 2-3 minutes without light control (seen 2026-11-17), so say it first (#218).
        note = "Install restarts the bridge (2-3 min without control). "
        if fw.get("autoinstall") and fw.get("autoinstall_time"):
            note += f"Night install is on at {fw['autoinstall_time']}. "
        return (note + text)[:SUMMARY_MAX]

    @property
    def extra_state_attributes(self):
        fw = self.resource() or {}
        return {"ready": [d.get("name") for d in fw.get("ready") or []],
                "pending": [d.get("name") for d in fw.get("pending") or []], "autoinstall": fw.get("autoinstall"),
                "autoinstall_time": fw.get("autoinstall_time")}

    async def async_install(self, version, backup, **kwargs) -> None:
        await self.coordinator.async_write("POST", f"/bridges/{seg(self.bridge)}/updates/install", {"confirm": True})
