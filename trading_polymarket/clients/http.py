"""A small, dependency-free async JSON/text HTTP client for free public APIs.

Every data source this module uses is free and keyless (docs/DATA-SOURCES.md),
so the client carries no credentials. What it does carry:

* **pacing**: at most one request per ``min_interval`` seconds per host, well
  inside every provider's published limit;
* **retries**: on HTTP 429 / 5xx and network errors, with growing waits
  (``backoff`` doubled per attempt, capped at ``max_backoff``); a
  ``Retry-After`` header is honoured, but a ``0`` there is never trusted
  (pumpfun learning "Probe Free APIs Before Picking Defaults");
* **counters**: requests, retries and failures, shown on the dashboard.

The transport is injectable, so tests never touch the network. The default
runs ``urllib`` in a worker thread, keeping the event loop free.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit

USER_AGENT = "trading-polymarket/0.1 (+paper research)"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[str, float, Mapping[str, str]], Awaitable[Response]]


class HttpError(RuntimeError):
    """A request that failed for good (after retries, or a non-retryable status)."""

    def __init__(self, message: str, *, status: int | None = None, url: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url


def _fetch(url: str, timeout: float, headers: Mapping[str, str]) -> Response:
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return Response(reply.status, reply.read(), dict(reply.headers))
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.read() or b"", dict(exc.headers or {}))


async def urllib_transport(
    url: str, timeout: float, headers: Mapping[str, str]
) -> Response:
    """The default transport: blocking ``urllib`` in a worker thread."""
    return await asyncio.to_thread(_fetch, url, timeout, headers)


def build_url(base: str, path: str, params: Mapping[str, Any] | None = None) -> str:
    """``base`` + ``path`` + a query string; ``None`` params are dropped."""
    url = base.rstrip("/") + "/" + path.lstrip("/")
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        for key, value in list(clean.items()):
            if isinstance(value, bool):
                clean[key] = "true" if value else "false"
        if clean:
            url += "?" + urlencode(clean, doseq=True)
    return url


class JsonHttp:
    """Paced, retrying GET client; see the module docstring."""

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        timeout: float = 15.0,
        max_retries: int = 3,
        backoff: float = 0.5,
        max_backoff: float = 8.0,
        min_interval: float = 0.05,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        self.transport = transport or urllib_transport
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.max_backoff = max_backoff
        self.min_interval = min_interval
        self.sleep = sleep or asyncio.sleep
        self.clock = clock
        self._next_slot: dict[str, float] = {}
        self.requests = 0
        self.retries = 0
        self.failures = 0
        self.last_error = ""

    async def _pace(self, host: str) -> None:
        now = self.clock()
        slot = max(now, self._next_slot.get(host, 0.0))
        self._next_slot[host] = slot + self.min_interval
        if slot > now:
            await self.sleep(slot - now)

    def _wait(self, attempt: int, response: Response | None) -> float:
        wait = min(self.max_backoff, self.backoff * 2**attempt)
        if response is not None:
            raw = response.headers.get("Retry-After") or response.headers.get(
                "retry-after"
            )
            try:
                asked = float(raw) if raw is not None else 0.0
            except ValueError:
                asked = 0.0
            wait = max(wait, min(asked, 60.0))
        return wait

    async def get(self, url: str) -> bytes:
        """The body of ``url``; raises :class:`HttpError` when it cannot be read."""
        host = urlsplit(url).netloc
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json, */*"}
        attempt = 0
        while True:
            await self._pace(host)
            self.requests += 1
            response: Response | None
            try:
                response = await self.transport(url, self.timeout, headers)
            except (OSError, TimeoutError) as exc:
                response = None
                error = f"{type(exc).__name__}: {exc}"
            else:
                if 200 <= response.status < 300:
                    return response.body
                error = f"HTTP {response.status}"
                if response.status not in RETRY_STATUSES:
                    self.failures += 1
                    self.last_error = f"{error} {url}"
                    raise HttpError(error, status=response.status, url=url)
            if attempt >= self.max_retries:
                self.failures += 1
                self.last_error = f"{error} {url}"
                raise HttpError(
                    f"{error} after {attempt + 1} attempts",
                    status=response.status if response is not None else None,
                    url=url,
                )
            self.retries += 1
            await self.sleep(self._wait(attempt, response))
            attempt += 1

    async def get_json(self, url: str) -> Any:
        body = await self.get(url)
        try:
            return json.loads(body)
        except ValueError as exc:
            self.failures += 1
            raise HttpError(f"invalid JSON from {url}: {exc}", url=url) from exc

    async def get_text(self, url: str) -> str:
        return (await self.get(url)).decode("utf-8", errors="replace")

    def stats(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "retries": self.retries,
            "failures": self.failures,
            "last_error": self.last_error,
        }


__all__ = [
    "RETRY_STATUSES",
    "USER_AGENT",
    "HttpError",
    "JsonHttp",
    "Response",
    "Transport",
    "build_url",
    "urllib_transport",
]
