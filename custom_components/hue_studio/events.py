"""The bridge event streams hue-web relays: a refresh on configuration events, so the poll can relax to 5 minutes.

One task per bridge, started after the first refresh and cancelled on unload. A broken stream reconnects with a growing
pause (5 s doubling to 5 min); while any stream is down the bridges coordinator polls every 60 s again.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta

import aiohttp

from .const import SCAN_INTERVAL, STREAM_SCAN_INTERVAL
from .coordinator import seg
from .model import needs_refresh, needs_slow_reads, smart_scene_states

_LOGGER = logging.getLogger(__name__)
BACKOFF_START, BACKOFF_MAX = 5, 300


class EventStreams:
    def __init__(self, hass, entry, runtime) -> None:
        self.hass, self.entry, self.rt = hass, entry, runtime
        self.up: set[str] = set()
        self.refreshes = 0               # how many refreshes the streams asked for (diagnostics)
        self.patched = 0                 # smart scene starts/stops applied from the event, no read (diagnostics)
        self._sleep = asyncio.sleep      # tests replace the pause between reconnects

    def start(self) -> None:
        for name in self.rt.bridges.data or {}:
            self.entry.async_create_background_task(self.hass, self._run(name), f"hue_studio events {name}")

    def _set_interval(self) -> None:
        names = set(self.rt.bridges.data or {})
        streams_up = bool(names) and names <= self.up
        self.rt.bridges.update_interval = timedelta(seconds=STREAM_SCAN_INTERVAL if streams_up else SCAN_INTERVAL)

    async def _run(self, name: str) -> None:
        pause = BACKOFF_START
        while True:
            try:
                await self._listen(name)
                pause = BACKOFF_START             # a stream that ended cleanly after working starts the count again
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as exc:
                _LOGGER.debug("event stream of %s: %s", name, exc)
            finally:
                self.up.discard(name)
                self._set_interval()
            await self._sleep(pause)
            pause = min(pause * 2, BACKOFF_MAX)

    async def _listen(self, name: str) -> None:
        url = f"{self.rt.api.base}/api/v1/bridges/{seg(name)}/events"
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=300)
        async with self.rt.api.session.get(url, timeout=timeout, headers={"Accept": "text/event-stream"}) as resp:
            resp.raise_for_status()
            self.up.add(name)
            self._set_interval()
            async for raw in resp.content:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    frame = json.loads(line[5:].strip())
                except ValueError:
                    continue
                states = smart_scene_states(frame)
                if states and self.rt.bridges.patch_smart_scenes(name, states):
                    self.patched += 1
                    continue
                if needs_refresh(frame):
                    self.refreshes += 1
                    if needs_slow_reads(frame):
                        self.rt.bridges.slow_stale(name)      # rules, firmware or scene usage changed too
                    await self.rt.bridges.async_request_bridge(name)     # debounced (2 s), only this bridge (#218)
