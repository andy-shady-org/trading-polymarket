from __future__ import annotations

import json
from typing import Any

from trading_polymarket.module import PolymarketModule
from trading_polymarket.research.recorder import record, record_cycle
from trading_polymarket.tests.support.factories import (
    NOW,
    book_payload,
    forecast_payload,
    metar_row,
    weather_event,
)
from trading_polymarket.tests.support.fakes import Clock, FakeTransport, fake_http


def module(**settings: Any) -> PolymarketModule:
    transport = FakeTransport(
        {
            "/events/keyset": {"events": [weather_event()]},
            "/v1/forecast": forecast_payload(),
            "/api/data/metar": [metar_row(NOW - 3600)],
            "/book": book_payload(bids=[(0.08, 500)], asks=[(0.10, 500)]),
        }
    )
    return PolymarketModule(
        http=fake_http(transport),
        clock=Clock(NOW),
        stations={"KDAL": {"lat": 1, "lon": 2}},
        **settings,
    )


async def test_record_cycle_reports_signals_and_rejections() -> None:
    row = await record_cycle(
        module(weather={"models": ["ecmwf_ifs025", "gfs_seamless"]})
    )
    assert row["timestamp"] == NOW and row["signals"]
    assert row["signals"][0]["strategy"] == "weather"
    empty = await record_cycle(module(weather={"enabled": False}))
    assert empty["signals"] == [] and empty["rejections"] == {}


async def test_record_writes_one_line_per_cycle(tmp_path) -> None:  # noqa: ANN001
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    lines: list[str] = []
    total = await record(
        module(weather={"models": ["ecmwf_ifs025", "gfs_seamless"]}),
        directory=tmp_path,
        cycles=2,
        interval=10,
        sleep=sleep,
        progress=lines.append,
    )
    rows = [
        json.loads(x) for x in (tmp_path / "2026-10-28.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 2 and total == sum(len(r["signals"]) for r in rows)
    assert len(waits) == 1 and 0 <= waits[0] <= 10 and len(lines) == 2
    assert await record(module(weather={"enabled": False}), directory=tmp_path) == 0
