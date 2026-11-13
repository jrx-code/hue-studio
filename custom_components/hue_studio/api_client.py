"""Thin client of the hue-web /api/v1 (the one process that talks to the bridges).

Stdlib only. `request` is blocking: callers run it in the executor. A `transport` can replace the network (tests run the
real hue-web app behind it): it takes (method, url, headers, body bytes) and returns (status, body bytes).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


MAX_BODY = 8 * 1024 * 1024   # the biggest answer (state of the main bridge) is well under this


class ApiError(Exception):
    """hue-web answered with an error (or could not be reached: status 504)."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def _detail(raw: bytes) -> str:
    try:
        data = json.loads(raw)
    except ValueError:
        return raw[:200].decode("utf-8", "replace")
    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, str):
        return detail
    return json.dumps(detail if detail is not None else data)[:300]


class HueWebClient:
    def __init__(self, base_url: str, timeout: float = 20, transport=None):
        if urllib.parse.urlsplit(base_url).scheme not in ("http", "https"):
            raise ApiError("the hue-web address must start with http:// or https://", 400)   # urllib would also open file://
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport or self._http

    def _http(self, method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, bytes]:
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read(MAX_BODY)
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read(MAX_BODY)

    def request(self, method: str, path: str, body=None, *, dry_run: bool = False, query: dict | None = None):
        """JSON in, JSON out. With `dry_run` the answer is {dry_run: true, writes: [...], result: ...}."""
        url = self.base + "/api/v1" + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if dry_run:
            headers["X-Hue-Dry-Run"] = "1"
        try:
            status, raw = self._transport(method, url, headers, data)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ApiError(f"hue-web unreachable: {exc}", 504) from None
        if status >= 400:
            raise ApiError(_detail(raw), status)
        return json.loads(raw) if raw else None

    def get(self, path: str, **query):
        return self.request("GET", path, query=query or None)

    def write(self, method: str, path: str, body=None, *, dry_run: bool = False) -> dict:
        """A write: always answers {dry_run, writes?, result}, so callers treat both modes alike."""
        out = self.request(method, path, body, dry_run=dry_run)
        if dry_run:
            return out
        return {"dry_run": False, "result": out}
