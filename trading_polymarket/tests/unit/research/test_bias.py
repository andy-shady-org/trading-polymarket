from __future__ import annotations

import json
from typing import Any

import pytest

from trading_polymarket.clients.weather import WeatherClient
from trading_polymarket.research.bias import (
    build_bias_table,
    save_table,
    station_errors,
    summarise,
)
from trading_polymarket.tests.support.factories import NOW, metar_row
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http

STATION = {"lat": 51.5, "lon": 0.05}
DAY = 86400.0
# 2026-10-26 00:00 UTC (London is UTC+0 after 25 October).
D26 = NOW - 2 * DAY - 12 * 3600


def previous(models: dict[str, float]) -> dict:
    times = [f"2026-10-26T{h:02d}:00" for h in range(24)] + ["2026-10-27T12:00"]
    hourly: dict[str, list[Any]] = {"time": times}
    for model, top in models.items():
        hourly[f"temperature_2m_previous_day1_{model}"] = [top - 1] * 23 + [top, top]
    return {"timezone": "Europe/London", "utc_offset_seconds": 0, "hourly": hourly}


def metars(hours: int, temp_tenths: int = 160, start: float = D26) -> list[dict]:
    return [
        metar_row(
            start + h * 3600,
            raw=f"METAR EGLC 26{h:02d}50Z 20/10 RMK T0{temp_tenths:03d}0100",
            icao="EGLC",
        )
        for h in range(hours)
    ]


def client(prev: dict, rows: list[dict]) -> WeatherClient:
    transport = FakeTransport({"previous-runs": prev, "/api/data/metar": rows})
    return WeatherClient(
        fake_http(transport, max_retries=0),
        previous_runs_url="https://previous-runs.test",
    )


async def test_station_errors_compare_metar_max_with_the_day_ahead_mean() -> None:
    rows = metars(20) + [metar_row(D26 + 5 * 3600, raw="SPECI X 30/10", kind="SPECI")]
    rows += metars(3, start=D26 + DAY)  # the 27th is incomplete: skipped
    rows += metars(2, start=NOW)  # today: skipped
    rows += [metar_row(D26, raw="METAR EGLC NO TEMP", icao="EGLC")]
    errors = await station_errors(
        client(previous({"a": 15.0, "b": 14.0}), rows),
        "EGLC",
        STATION,
        models=("a", "b"),
        now=NOW,
    )
    assert errors == {"2026-10-26": pytest.approx(16.0 - 14.5)}


async def test_days_without_a_forecast_are_skipped() -> None:
    errors = await station_errors(
        client(previous({}), metars(20)), "EGLC", STATION, models=("a",), now=NOW
    )
    assert errors == {}


def test_summarise() -> None:
    assert summarise({}) == {"bias": 0.0, "sd": 0.0, "mae": 0.0, "n": 0}
    one = summarise({"a": 1.0})
    assert one["sd"] == 0.0 and one["n"] == 1
    two = summarise({"a": 1.0, "b": -3.0})
    assert two == {
        "bias": -1.0,
        "sd": pytest.approx(2.828, abs=1e-3),
        "mae": 2.0,
        "n": 2,
    }


async def test_build_and_save_table(tmp_path) -> None:  # noqa: ANN001
    lines: list[str] = []
    table = await build_bias_table(
        client(previous({"a": 15.0}), metars(20)),
        {"EGLC": STATION, "BAD": {}},
        models=("a",),
        progress=lines.append,
    )
    assert table["stations"]["EGLC"]["n"] == 1
    assert "BAD" in table["failures"] and lines and "EGLC" in lines[0]
    path = save_table(table, tmp_path / "x" / "bias.json")
    assert json.loads(open(path).read())["models"] == ["a"]
    quiet = await build_bias_table(
        client(previous({"a": 15.0}), metars(20)), {"EGLC": STATION}, models=("a",)
    )
    assert quiet["failures"] == {}
