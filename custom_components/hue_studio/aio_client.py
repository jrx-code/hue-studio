"""Async client of the hue-web /api/v1 on Home Assistant's shared aiohttp session (entities, services, event stream).

The websocket commands still use the blocking `HueWebClient`; both raise `ApiError` with the hue-web detail.
"""
from __future__ import annotations

import asyncio
import json

import aiohttp

from .api_client import MAX_BODY, ApiError, _detail

TIMEOUT = 20


class AsyncHueWeb:
    def __init__(self, session: aiohttp.ClientSession, base_url: str, timeout: float = TIMEOUT) -> None:
        self.session = session
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    async def request(self, method: str, path: str, body=None, *, dry_run: bool = False, query: dict | None = None):
        headers = {"Accept": "application/json"}
        if dry_run:
            headers["X-Hue-Dry-Run"] = "1"
        try:
            async with asyncio.timeout(self.timeout):
                async with self.session.request(method, self.base + "/api/v1" + path, params=query, json=body,
                                                headers=headers) as resp:
                    status = resp.status
                    if resp.content_length is not None and resp.content_length > MAX_BODY:
                        raise ApiError(f"hue-web answer too large ({resp.content_length} bytes)", 502)
                    buf = bytearray()          # content.read(n) returns one chunk, not n bytes: read to the end
                    async for chunk in resp.content.iter_chunked(65536):
                        buf += chunk
                        if len(buf) > MAX_BODY:
                            raise ApiError("hue-web answer too large", 502)
                    raw = bytes(buf)
        except (aiohttp.ClientError, TimeoutError, OSError) as exc:
            raise ApiError(f"hue-web unreachable: {exc or type(exc).__name__}", 504) from None
        if status >= 400:
            raise ApiError(_detail(raw), status)
        try:
            return json.loads(raw) if raw else None
        except ValueError as exc:
            raise ApiError(f"hue-web answered no JSON: {exc}", 502) from None

    async def get(self, path: str, **query):
        return await self.request("GET", path, query=query or None)

    async def write(self, method: str, path: str, body=None, *, dry_run: bool = False) -> dict:
        """Both modes answer {dry_run, writes?, result}."""
        out = await self.request(method, path, body, dry_run=dry_run)
        return out if dry_run else {"dry_run": False, "result": out}
