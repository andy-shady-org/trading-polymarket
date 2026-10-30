from __future__ import annotations

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.weather import Metar, PreviousRuns, WeatherClient
from trading_polymarket.config import WeatherLane
from trading_polymarket.research.records import append_jsonl
from trading_polymarket.research.weather_backtest import (
    BucketHistory,
    EventHistory,
    _observed_max,
    backtest_weather,
    collect_weather,
    day_ahead_forecasts,
    load_events,
    station_metars,
)
from trading_polymarket.tests.support.factories import NOW, metar_row, weather_event
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http

LANE = WeatherLane(models=("a",), market_weight=0.0, max_edge=0.9, min_edge=0.05)
CHICAGO = PreviousRuns("America/Chicago", -18000, {"a": {}})


def event_row(day: str = "2026-10-20", winner: int = 2, price: float = 0.1) -> dict:
    labels = [(None, 73), (74, 75), (76, 77), (78, None)]
    start = NOW - 30 * 86400
    return {
        "event_id": day,
        "title": "t",
        "city": "Dallas",
        "icao": "KDAL",
        "unit": "F",
        "day": day,
        "end_time": NOW,
        "buckets": [
            {
                "low": low,
                "high": high,
                "yes_token": f"y{i}{day}",
                "no_token": f"n{i}{day}",
                "won": i == winner,
                "history": [[start, price]],
            }
            for i, (low, high) in enumerate(labels)
        ],
    }


def test_event_history_parsing_labels_and_settlement(tmp_path) -> None:  # noqa: ANN001
    event = EventHistory.from_dict(event_row())
    assert [b.label("F") for b in event.buckets] == [
        "<=73°F",
        "74-75°F",
        "76-77°F",
        ">=78°F",
    ]
    assert BucketHistory(5, 5, "y", "n", False, ()).label("C") == "5°C"
    assert event.settled_celsius() == pytest.approx((76.5 - 32) * 5 / 9)
    assert EventHistory.from_dict(event_row(winner=0)).settled_celsius() is None
    assert EventHistory.from_dict(event_row(winner=9)).settled_celsius() is None
    assert event.buckets[0].price_at(0) is None
    path = tmp_path / "w.jsonl"
    append_jsonl(path, [event_row("2026-10-21"), {"bad": 1}, event_row("2026-10-20")])
    assert [e.day for e in load_events(path)] == [
        date(2026, 10, 20),
        date(2026, 10, 21),
    ]


def runs(**days: float) -> dict[str, PreviousRuns]:
    return {
        "KDAL": PreviousRuns(
            "America/Chicago",
            -18000,
            {"a": {d.replace("_", "-"): v for d, v in days.items()}},
        )
    }


def test_backtest_buys_the_bucket_the_forecast_favours() -> None:
    # Forecast 24.7°C = 76.5°F: 76-77°F is likely but priced at 0.10.
    events = [EventHistory.from_dict(event_row())]
    result = backtest_weather(events, runs(**{"2026_10_20": 24.7}), LANE, bankroll=1000)
    assert result.trades >= 1 and result.markets == 1
    assert (
        result.scores["buckets"] == 4
        and result.scores["model"] < result.scores["market"]
    )
    names = [
        r["payload"]["name"] for r in result.records if r["payload"]["action"] == "buy"
    ]
    assert "Dallas 20 Oct 76-77°F" in names
    assert result.net > 0


def test_backtest_learns_bias_only_from_earlier_events() -> None:
    days = [f"2026-10-{d:02d}" for d in range(1, 13)]
    events = [EventHistory.from_dict(event_row(d)) for d in days]
    forecasts = runs(**{d.replace("-", "_"): 22.0 for d in days})
    result = backtest_weather(events, forecasts, LANE)
    first = [r for r in result.records if r["payload"]["action"] == "buy"]
    mus = sorted({r["payload"]["entry_metrics"]["mu_c"] for r in first})
    assert mus[0] == 22.0 and mus[-1] > 22.0  # bias applied after 5 events
    open_ended = [EventHistory.from_dict(event_row(d, winner=3)) for d in days]
    flat = backtest_weather(open_ended, forecasts, LANE)
    flat_mus = {
        r["payload"]["entry_metrics"]["mu_c"]
        for r in flat.records
        if r["payload"]["action"] == "buy"
    }
    assert flat_mus == {22.0}  # an open-ended winner teaches no bias


def test_backtest_skips_missing_forecasts_prices_and_guards() -> None:
    events = [EventHistory.from_dict(event_row())]
    assert backtest_weather(events, {}, LANE).trades == 0
    assert backtest_weather(events, runs(), LANE).markets == 0
    late = [EventHistory.from_dict(event_row(price=0.1))]
    late[0].buckets[0].history  # noqa: B018
    no_price = EventHistory.from_dict(
        {**event_row(), "buckets": [{**event_row()["buckets"][0], "history": []}]}
    )
    assert backtest_weather([no_price], runs(**{"2026_10_20": 24.7}), LANE).trades == 0
    guarded = WeatherLane(models=("a",), max_edge=0.07, min_edge=0.06)
    assert backtest_weather(late, runs(**{"2026_10_20": 24.7}), guarded).trades == 0
    small = WeatherLane(models=("a",), market_weight=0.0, max_edge=0.9, min_notional=14)
    assert (
        backtest_weather(late, runs(**{"2026_10_20": 24.7}), small, bankroll=10).trades
        == 0
    )
    band = WeatherLane(models=("a",), market_weight=0.0, max_edge=0.9, min_price=0.5)
    cheap = [EventHistory.from_dict(event_row(price=0.3))]
    result = backtest_weather(cheap, runs(**{"2026_10_20": 24.7}), band)
    assert all(
        r["payload"]["price"] >= 0.5
        for r in result.records
        if r["payload"]["action"] == "buy"
    )


async def test_collect_weather_appends_resolved_metar_events(
    tmp_path,
) -> None:  # noqa: ANN001
    done = weather_event()
    for raw in done["markets"]:
        raw.update(closed=True, outcomePrices='["0","1"]')
    done["markets"][2]["outcomePrices"] = '["1","0"]'
    pending = weather_event(day="October 29")
    pending["id"] = "9002"
    other = weather_event(city="London", day="October 27")
    other["id"] = "9003"
    for raw in other["markets"]:
        raw.update(closed=True, outcomePrices='["0","1"]')
    broken = weather_event(city="Paris", day="October 26")
    broken["id"] = "9004"
    for raw in broken["markets"]:
        raw.update(closed=True, outcomePrices='["0","1"]', clobTokenIds='["77","78"]')
    junk = {"title": "Will it rain?", "markets": []}

    def history(url: str) -> object:
        return (
            OSError("x") if "market=77" in url else {"history": [{"t": NOW, "p": 0.2}]}
        )

    transport = FakeTransport(
        {
            "/events/keyset": {"events": [done, pending, other, broken, junk]},
            "/prices-history": history,
        }
    )
    http = fake_http(transport, max_retries=0)
    path = tmp_path / "w.jsonl"
    lines: list[str] = []
    written = await collect_weather(
        GammaClient(http),
        ClobClient(http),
        start=date(2026, 10, 1),
        end=date(2026, 10, 28),
        path=path,
        cities=["Dallas", "Paris"],
        progress=lines.append,
    )
    assert written == 1
    (event,) = load_events(path)
    assert event.icao == "KDAL" and [b.won for b in event.buckets] == [
        False,
        False,
        True,
        False,
    ]
    assert any("Paris" in line for line in lines)
    again = await collect_weather(
        GammaClient(http),
        ClobClient(http),
        start=date(2026, 10, 1),
        end=date(2026, 10, 28),
        path=path,
        cities=["Dallas", "Paris"],
    )
    assert again == 0
    quiet = await collect_weather(
        GammaClient(http),
        ClobClient(http),
        start=date(2026, 10, 1),
        end=date(2026, 10, 28),
        path=tmp_path / "quiet.jsonl",
        cities=["Dallas"],
    )
    assert quiet == 1


@pytest.mark.regression("TP-4")
async def test_events_without_prices_are_not_stored(tmp_path) -> None:  # noqa: ANN001
    done = weather_event()
    for raw in done["markets"]:
        raw.update(closed=True, outcomePrices='["0","1"]')
    transport = FakeTransport(
        {"/events/keyset": {"events": [done]}, "/prices-history": {"history": []}}
    )
    http = fake_http(transport)
    path = tmp_path / "w.jsonl"
    lines: list[str] = []
    args: dict[str, Any] = {
        "start": date(2026, 10, 1),
        "end": date(2026, 10, 28),
        "path": path,
    }
    assert await collect_weather(GammaClient(http), ClobClient(http), **args) == 0
    assert (
        await collect_weather(
            GammaClient(http), ClobClient(http), progress=lines.append, **args
        )
        == 0
    )
    assert load_events(path) == [] and "no price history" in lines[0]
    assert all("startTs=" in url for url in transport.calls if "prices-history" in url)


async def test_day_ahead_forecasts_per_station() -> None:
    payload = {
        "timezone": "UTC",
        "hourly": {
            "time": ["2026-10-20T12:00"],
            "temperature_2m_previous_day1": [20.0],
        },
    }
    client = WeatherClient(fake_http(FakeTransport({"/v1/forecast": payload})))
    found = await day_ahead_forecasts(
        client,
        {"KDAL": {"lat": 1, "lon": 2}},
        ["KDAL", "KDAL", "XXXX"],
        models=("a",),
        past_days=10,
    )
    assert list(found) == ["KDAL"] and found["KDAL"].mean("2026-10-20") == 20.0
    broken = WeatherClient(
        fake_http(FakeTransport({"/v1/forecast": OSError("x")}), max_retries=0)
    )
    lines: list[str] = []
    stations = {"KDAL": {"lat": 1, "lon": 2}}
    args: dict[str, Any] = {"models": ("a",), "past_days": 10}
    assert await day_ahead_forecasts(broken, stations, ["KDAL"], **args) == {}
    found = await day_ahead_forecasts(
        broken, stations, ["KDAL"], progress=lines.append, **args
    )
    assert found == {} and "KDAL" in lines[0]


# 2026-10-20 in Dallas (UTC-5): local midnight is 05:00 UTC.
D20 = 1792472400.0


def metar(hours_after_midnight: float, temp: float, routine: bool = True) -> Metar:
    return Metar("KDAL", D20 + hours_after_midnight * 3600, temp, "raw", routine)


def intraday_runs(top: float = 22.0) -> dict[str, PreviousRuns]:
    hourly = {f"2026-10-20T{h:02d}:00": top - abs(15 - h) for h in range(24)}
    return {
        "KDAL": PreviousRuns(
            "America/Chicago",
            -18000,
            {"a": {"2026-10-20": top}},
            hourly={"a": hourly},
        )
    }


def test_observed_max_before_the_entry() -> None:
    zone = ZoneInfo("America/Chicago")
    rows = [metar(10, 20.0), metar(12, 26.0, routine=False), metar(17, 30.0)]
    assert _observed_max(rows, date(2026, 10, 20), zone, D20 + 16 * 3600) == (
        True,
        20.0,
    )
    assert _observed_max([], date(2026, 10, 20), zone, D20) == (False, None)
    other_day = [metar(30, 20.0)]
    assert _observed_max(other_day, date(2026, 10, 20), zone, D20) == (False, None)


def test_intraday_backtest_uses_the_observed_floor() -> None:
    # 26.5°C observed by 16:00 = 79.7°F: only ">=78°F" can still win.
    events = [EventHistory.from_dict(event_row(winner=3, price=0.5))]
    obs = {"KDAL": [metar(14, 26.5)]}
    result = backtest_weather(
        events, intraday_runs(), LANE, entry_hour=16, observations=obs
    )
    assert result.markets == 1 and result.trades >= 1
    buys = [r["payload"] for r in result.records if r["payload"]["action"] == "buy"]
    assert any(b["name"].endswith(">=78°F") for b in buys)
    assert all(b["entry_metrics"]["model_p"] > 0.5 for b in buys)
    # Remaining hours peak at 21; the hours gone forecast 22 against 26.5
    # observed: half of that 4.5 error carries (TP-11), sigma is intraday.
    assert {b["entry_metrics"]["mu_c"] for b in buys} == {23.25}
    assert {b["entry_metrics"]["sigma_c"] for b in buys} == {LANE.intraday_sigma}


def test_intraday_backtest_before_the_days_first_metar() -> None:
    # METARs cover the day but none is before 09:00: the forecast-only
    # fallback, as the live lane prices it, with the bias up to the peak.
    events = [EventHistory.from_dict(event_row(winner=3, price=0.5))]
    obs = {"KDAL": [metar(17, 26.5)]}
    result = backtest_weather(
        events, intraday_runs(), LANE, entry_hour=9, observations=obs
    )
    assert result.markets == 1


def test_intraday_backtest_skips_days_without_metars_or_hours() -> None:
    events = [EventHistory.from_dict(event_row())]
    assert (
        backtest_weather(
            events, intraday_runs(), LANE, entry_hour=16, observations={}
        ).markets
        == 0
    )
    no_hours = intraday_runs()
    no_hours["KDAL"] = PreviousRuns(
        "America/Chicago", -18000, {"a": {"2026-10-20": 22.0}}
    )
    obs = {"KDAL": [metar(14, 26.5)]}
    assert (
        backtest_weather(
            events, no_hours, LANE, entry_hour=16, observations=obs
        ).markets
        == 0
    )


async def test_station_metars() -> None:
    good = WeatherClient(
        fake_http(FakeTransport({"/api/data/metar": [metar_row(NOW)]}))
    )
    found = await station_metars(good, ["KDAL", "KDAL"])
    assert list(found) == ["KDAL"] and len(found["KDAL"]) == 1
    bad = WeatherClient(
        fake_http(FakeTransport({"/api/data/metar": OSError("x")}), max_retries=0)
    )
    assert await station_metars(bad, ["KDAL"]) == {}
    lines: list[str] = []
    assert await station_metars(bad, ["KDAL"], progress=lines.append) == {}
    assert "KDAL" in lines[0]
