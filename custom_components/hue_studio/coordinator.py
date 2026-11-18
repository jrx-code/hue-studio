"""Two coordinators per hue-web: the bridges (state and scene capacity) and the hub scenes, which span the bridges."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, replace
from datetime import timedelta
from urllib.parse import quote

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .aio_client import AsyncHueWeb
from .api_client import ApiError, HueWebClient
from .const import CAPACITY_EVERY, DOMAIN, HUB_SCAN_INTERVAL, SCAN_INTERVAL
from .model import Snapshot, hub_scenes

_LOGGER = logging.getLogger(__name__)
RETRY_PAUSE = 3   # seconds before the one retry of a refused PUT


def seg(value: str) -> str:
    return quote(str(value), safe="")


class _Base(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry, api: AsyncHueWeb, name: str, seconds: int) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN} {name}", update_interval=timedelta(seconds=seconds), config_entry=entry,
                         always_update=False,
                         request_refresh_debouncer=Debouncer(hass, _LOGGER, cooldown=2, immediate=False))
        self.api = api
        self.reads = 0          # complete answers so far (the registry cleanup needs two fresh reads, not two callbacks)

    async def async_write(self, method: str, path: str, body=None, *, dry_run: bool = False) -> dict:
        """A write through hue-web; a real one asks for a (debounced) refresh so the entities show the result."""
        try:
            try:
                out = await self.api.write(method, path, body, dry_run=dry_run)
            except ApiError as exc:
                # A bridge refuses a setting written again within seconds ("cannot be written", seen on a motion sensor
                # on VM 103); a PUT sets an absolute value, so one retry after a pause is safe.
                if method != "PUT" or "cannot be written" not in str(exc):
                    raise
                await asyncio.sleep(RETRY_PAUSE)
                out = await self.api.write(method, path, body, dry_run=dry_run)
        except ApiError as exc:
            raise HomeAssistantError(f"Hue Studio: {exc}") from exc
        if not dry_run:
            await self.async_request_refresh()
        return out


# Reads that change rarely, every CAPACITY_EVERY seconds per bridge (and after a write or a configuration event):
# Snapshot field -> (path under /bridges/{b}, query). A failed one keeps its last answer; the state still updates.
SLOW_READS = {
    "capacity": ("/capacity", {}),
    "updates": ("/updates", {"notes": "false"}),
    "usage": ("/usage", {"version": 3}),
    "rules": ("/bridge-rules", {}),
}


ALL = object()      # a write asked: read every bridge


class BridgesCoordinator(_Base):
    """{bridge name: Snapshot}: every bridge hue-web serves."""

    def __init__(self, hass, entry, api) -> None:
        super().__init__(hass, entry, api, "bridges", SCAN_INTERVAL)
        self._slow_at: dict[str, float] = {}
        # Which bridges the next refresh reads: None = all (the poll), ALL = all (a write asked), or the names whose
        # event streams asked. A full state is 16 bridge requests, so an event re-reads only its own bridge (#218).
        self._only: set[str] | object | None = None
        self._full_at = 0.0
        self.state_reads: dict[str, int] = {}      # full state reads per bridge (diagnostics)

    def patch_smart_scenes(self, name: str, states: dict[str, str]) -> bool:
        """Apply smart scene states from an event to the last snapshot. False when a scene is unknown (then read).

        Sets the data without async_set_updated_data, which would push the next poll back on every event."""
        snap = (self.data or {}).get(name)
        rows = (snap.state.get("smart_scenes") if snap else None) or []
        if snap is None or not set(states) <= {r.get("id") for r in rows}:
            return False
        rows = [dict(r, state=states[r["id"]], active=states[r["id"]] == "active") if r.get("id") in states else r
                for r in rows]
        self.data = {**self.data, name: replace(snap, state={**snap.state, "smart_scenes": rows})}
        self.async_update_listeners()
        return True

    async def async_request_all(self) -> None:
        """A (debounced) refresh of every bridge, after a change made through hue-web."""
        self._only = ALL
        await self.async_request_refresh()

    async def async_request_bridge(self, name: str) -> None:
        """A (debounced) refresh of one bridge, asked by its event stream; other bridges keep their last snapshot."""
        if self._only is not ALL:
            self._only = (self._only if isinstance(self._only, set) else set()) | {name}
        await self.async_request_refresh()

    def slow_stale(self, name: str | None = None) -> None:
        """Read the slow parts again on the next refresh (of one bridge, or of all)."""
        if name is None:
            self._slow_at.clear()
        else:
            self._slow_at.pop(name, None)

    async def async_write(self, method: str, path: str, body=None, *, dry_run: bool = False) -> dict:
        if not dry_run:
            self.slow_stale()
            self._only = ALL
        return await super().async_write(method, path, body, dry_run=dry_run)

    def _scope(self, prev: dict) -> set[str] | None:
        """The bridges to read now, None for all. A poll that is due reads everything even when an event asked first."""
        only, self._only = self._only, None
        interval = self.update_interval.total_seconds() if self.update_interval else 0
        if not prev or not isinstance(only, set) or time.monotonic() - self._full_at >= interval * 0.9:
            return None
        return only

    async def _async_update_data(self) -> dict[str, Snapshot]:
        prev: dict[str, Snapshot] = self.data or {}
        out: dict[str, Snapshot] = {}
        try:
            names = (await self.api.get("/healthz") or {}).get("bridges") or []
            only = self._scope(prev)
            for name in names:
                if only is not None and name not in only and name in prev:
                    out[name] = prev[name]
                    continue
                self.state_reads[name] = self.state_reads.get(name, 0) + 1
                snap = Snapshot(name, await self.api.get(f"/bridges/{seg(name)}/state", version=3) or {})
                old = prev.get(name)
                now = time.monotonic()
                fresh = old is None or now - self._slow_at.get(name, 0) >= CAPACITY_EVERY
                for key, (path, query) in SLOW_READS.items():
                    value = getattr(old, key) if old is not None else None
                    if fresh:
                        try:
                            value = await self.api.get(f"/bridges/{seg(name)}{path}", **query)
                        except ApiError as exc:          # this part goes stale or unknown, the rest still updates
                            _LOGGER.debug("%s of %s: %s", key, name, exc)
                    setattr(snap, key, value)
                if fresh:
                    self._slow_at[name] = now
                out[name] = snap
        except ApiError as exc:
            raise UpdateFailed(str(exc)) from exc
        if only is None:
            self._full_at = time.monotonic()
        self.reads += 1
        return out


class HubCoordinator(_Base):
    """{hub scene id: summary}; None when this hue-web has no hub scenes yet (an older version)."""

    def __init__(self, hass, entry, api) -> None:
        super().__init__(hass, entry, api, "hub scenes", HUB_SCAN_INTERVAL)

    async def _async_update_data(self) -> dict[str, dict] | None:
        try:
            out = hub_scenes(await self.api.get("/hub-scenes"))
            self.reads += 1
            return out
        except ApiError as exc:
            if exc.status == 404:
                return None
            raise UpdateFailed(str(exc)) from exc


@dataclass
class StudioRuntime:
    api: AsyncHueWeb
    client: HueWebClient            # blocking client of the websocket commands
    bridges: BridgesCoordinator
    hub: HubCoordinator
    events: object = None           # EventStreams, once started
    cleanup: object = None          # RegistryCleanup, once started
