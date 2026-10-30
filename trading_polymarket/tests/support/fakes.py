"""Test doubles: a routed fake HTTP transport and a recording module host."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from trading_polymarket.clients.http import JsonHttp, Response

Route = Any  # a payload (dict/list/str/bytes), a Response, an exception or a callable


async def no_sleep(_: float) -> None:
    return None


def _as_response(value: Any) -> Response:
    if isinstance(value, Response):
        return value
    if isinstance(value, bytes):
        return Response(200, value)
    if isinstance(value, str):
        return Response(200, value.encode())
    return Response(200, json.dumps(value).encode())


@dataclass
class FakeTransport:
    """Answers by the first route whose key is a substring of the URL.

    A route's value may be a payload (JSON-encoded), a :class:`Response`, an
    exception instance (raised), a list (consumed one item per call; the last
    item repeats) or a callable taking the URL. Unrouted URLs answer 404.
    """

    routes: dict[str, Route] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def add(self, key: str, value: Route) -> FakeTransport:
        self.routes[key] = value
        return self

    def count(self, key: str) -> int:
        return sum(1 for url in self.calls if key in url)

    async def __call__(
        self, url: str, timeout: float, headers: Mapping[str, str]
    ) -> Response:
        self.calls.append(url)
        for key, value in self.routes.items():
            if key not in url:
                continue
            if isinstance(value, Sequenced):
                value = value.next()
            if callable(value) and not isinstance(value, Response):
                value = value(url)
            if isinstance(value, BaseException):
                raise value
            return _as_response(value)
        return Response(404, b"{}")


class Sequenced:
    """Route values returned one per call; the last one repeats."""

    def __init__(self, *values: Any) -> None:
        self.values = list(values)

    def next(self) -> Any:
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


def fake_http(transport: FakeTransport | None = None, **options: Any) -> JsonHttp:
    return JsonHttp(
        transport=transport or FakeTransport(),
        sleep=no_sleep,
        min_interval=0.0,
        **options,
    )


@dataclass
class RecordingHost:
    events: list[str] = field(default_factory=list)
    market_data: int = 0
    degraded: dict[str, bool] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)

    def notify_market_data(self) -> None:
        self.market_data += 1

    def record_event(self, message: str, *, alert: bool = False) -> None:
        self.events.append(message)

    def set_degraded(self, name: str, degraded: bool, detail: str = "") -> None:
        self.degraded[name] = degraded
        self.details[name] = detail


class Ticker:
    """An injectable ``sleep`` that returns only when :meth:`tick` is called."""

    def __init__(self) -> None:
        self.waits: list[float] = []
        self._event = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        await self._event.wait()
        self._event.clear()

    def tick(self) -> None:
        self._event.set()

    async def settle(self, waits: int) -> None:
        """Yield until ``waits`` sleeps have started (a loop pass is done)."""
        for _ in range(1000):
            if len(self.waits) >= waits:
                return
            await asyncio.sleep(0)
        raise AssertionError(f"{len(self.waits)} sleeps, expected {waits}")


class Clock:
    """A settable clock."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


__all__ = [
    "Clock",
    "FakeTransport",
    "RecordingHost",
    "Sequenced",
    "Ticker",
    "fake_http",
    "no_sleep",
]
