"""Unit tests for ``research/updown.py``: the Up/Down backfill (FEAT-146)."""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from trading_polymarket.clients.data_api import DataApiClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.http import Response
from trading_polymarket.clients.spot import SpotClient
from trading_polymarket.research import updown
from trading_polymarket.research.updown import (
    CollectResult,
    SpotDay,
    UpDownMarket,
    collect,
    collect_day,
    day_path,
    day_start,
    days,
    load_markets,
    load_spot,
    market_slugs,
    parse_day,
    spot_path,
)
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http

DAY = date(2026, 10, 5)
START = day_start(DAY)
LATER = START + 3 * 86400


def gamma_raw(start: float, **extra: Any) -> dict[str, Any]:
    return {
        "slug": f"btc-updown-5m-{int(start)}",
        "conditionId": f"0xc{int(start)}",
        "outcomes": '["Up", "Down"]',
        "outcomePrices": '["0", "1"]',
        "events": [{"eventMetadata": {"priceToBeat": 100.0, "finalPrice": 99.5}}],
        "feeSchedule": {"rate": 0.07},
        "volumeNum": 1234.5,
        **extra,
    }


def trade_row(t: float) -> dict[str, Any]:
    return {
        "timestamp": t,
        "outcome_index": 0,
        "side": "BUY",
        "price": 0.031,
        "size": 10.0,
        "proxy_wallet": "0xW",
    }


def clients(transport: FakeTransport) -> tuple[GammaClient, DataApiClient, SpotClient]:
    http = fake_http(transport, max_retries=0)
    return (
        GammaClient(http, base_url="https://g.test"),
        DataApiClient(http, base_url="https://d.test"),
        SpotClient(http, base_url="https://s.test"),
    )


def routes(markets: list[Any]) -> FakeTransport:
    return FakeTransport(
        {
            # Only the first batch of slugs holds the day's first markets.
            "/markets?": lambda url: (
                markets if f"slug=btc-updown-5m-{int(START)}&" in url else []
            ),
            "/v2/trades": {"data": [trade_row(START + 250)], "pagination": {}},
            "/api/v3/klines": lambda url: (
                [[int(START * 1000), "0", "0", "0", "100.0"]]
                if f"startTime={int(START * 1000)}&" in url
                else []
            ),
        }
    )


def test_slugs_paths_and_days() -> None:
    slugs = market_slugs("btc", "5m", DAY)
    assert len(slugs) == 288 and slugs[0] == f"btc-updown-5m-{int(START)}"
    assert slugs[1].endswith(str(int(START) + 300))
    assert len(market_slugs("eth", "15m", DAY)) == 96
    assert day_path("d", "btc", "5m", DAY) == Path("d/btc-5m/2026-10-05.jsonl.gz")
    assert spot_path("d", "BTCUSDT", DAY) == Path("d/spot/BTCUSDT-2026-10-05.json.gz")
    assert days(DAY, date(2026, 10, 7)) == [DAY, date(2026, 10, 6)]
    assert parse_day("2026-10-05") == DAY


def test_a_spot_day_answers_the_last_close() -> None:
    spot = SpotDay("BTCUSDT", 1000.0, (None, 5.0, None, 7.0))
    assert spot.price_at(999) is None and spot.price_at(1000) is None
    assert spot.price_at(1002.5) == 5.0 and spot.price_at(1003) == 7.0
    assert spot.price_at(9999) == 7.0
    assert SpotDay.from_dict(spot.to_dict()) == spot


@pytest.mark.parametrize(
    "extra",
    [
        {"outcomePrices": '["0.5", "0.5"]'},
        {"outcomes": '["Yes", "No"]'},
        {"outcomePrices": "not json"},
        {"conditionId": ""},
    ],
)
def test_unsettled_or_odd_markets_are_left_out(extra: dict[str, Any]) -> None:
    assert updown._settled(gamma_raw(START, **extra), 300) is None
    assert updown._winner({}) is None


def test_a_settled_market_without_metadata_or_fee() -> None:
    raw = gamma_raw(START, events=[], feeSchedule=None, volumeNum=None, volume="7")
    market = updown._settled(raw, 300)
    assert market is not None and market.winner == 1 and market.end == START + 300
    assert market.price_to_beat is None and market.fee_rate == 0.0
    assert market.volume == 7.0
    odd = updown._settled(gamma_raw(START, events=[{"eventMetadata": "x"}]), 300)
    assert odd is not None and odd.final_price is None
    bad = updown._settled(
        gamma_raw(START, events=[{"eventMetadata": {"priceToBeat": "x"}}]), 300
    )
    assert bad is not None and bad.price_to_beat is None


async def test_a_day_is_read_whole_and_written(tmp_path: Path) -> None:
    unsettled = gamma_raw(START + 600, outcomePrices='["0.5", "0.5"]')
    transport = routes([gamma_raw(START + 300), gamma_raw(START), unsettled])
    result = await collect_day(
        *clients(transport), asset="btc", window="5m", day=DAY, directory=tmp_path
    )
    assert (result.markets, result.unsettled, result.trades) == (2, 1, 2)
    assert transport.count("/markets?") == 3  # 288 slugs, 100 a request
    markets = list(load_markets(tmp_path, "btc", "5m"))
    assert [m.start for m in markets] == [START, START + 300]
    first = markets[0]
    assert first.trades == ((250.0, 0, 1, 0.031, 10.0, "0xw"),)
    assert (first.price_to_beat, first.final_price, first.fee_rate) == (100, 99.5, 0.07)
    assert UpDownMarket.from_dict(first.to_dict()) == first
    spot = load_spot(tmp_path, "BTCUSDT", DAY)
    assert spot is not None and spot.closes[0] == 100.0 and spot.closes[1] is None
    assert len(spot.closes) == 86400
    assert not list(tmp_path.rglob("*.part"))


def test_a_spot_candle_outside_the_day_is_dropped() -> None:
    spot = updown._spot_day("BTCUSDT", DAY, [(START - 1, 1.0), (START + 86400, 2.0)])
    assert all(c is None for c in spot.closes)


async def test_collect_skips_days_on_disk_running_and_failed(tmp_path: Path) -> None:
    calls: list[str] = []

    def failing_on_the_6th(url: str) -> Any:
        calls.append(url)
        if f"slug=btc-updown-5m-{int(START) + 86400}" in url:
            return Response(500, b"{}")
        return []

    transport = routes([])
    transport.routes["/markets?"] = failing_on_the_6th
    gamma, data, spot = clients(transport)
    day_path(tmp_path, "btc", "5m", DAY).parent.mkdir(parents=True)
    day_path(tmp_path, "btc", "5m", DAY).write_bytes(gzip.compress(b""))
    lines: list[str] = []
    result = await collect(
        gamma,
        data,
        spot,
        asset="btc",
        window="5m",
        start=DAY,
        end=date(2026, 10, 9),
        directory=tmp_path,
        progress=lines.append,
        now=LATER + 3600,
    )
    assert result.days_skipped == 1 and result.days_failed == ["2026-10-06"]
    assert result.days_written == 1 and result.markets == 0
    assert lines[0].startswith("2026-10-06: not written (HTTP 500")
    assert lines[1] == "2026-10-07: 0 markets, 0 trades"
    assert lines[2] == "2026-10-08: not over yet, left out"
    # Quietly, with the real clock: every day of 2026-10 is long over.
    again = await collect(
        gamma,
        data,
        spot,
        asset="btc",
        window="5m",
        start=DAY,
        end=date(2026, 10, 8),
        directory=tmp_path,
    )
    assert again == CollectResult(days_skipped=2, days_failed=["2026-10-06"])


async def test_unsettled_markets_are_counted_and_reported(tmp_path: Path) -> None:
    transport = routes([gamma_raw(START, outcomePrices='["0", "0"]')])
    lines: list[str] = []
    result = await collect(
        *clients(transport),
        asset="btc",
        window="5m",
        start=DAY,
        end=date(2026, 10, 6),
        directory=tmp_path,
        progress=lines.append,
    )
    assert result.unsettled == 1 and lines == [
        "2026-10-05: 0 markets, 0 trades, 1 not settled"
    ]


async def test_unknown_assets_and_windows_are_refused(tmp_path: Path) -> None:
    gamma, data, spot = clients(FakeTransport())
    with pytest.raises(ValueError, match="unknown asset 'ada'"):
        await collect(gamma, data, spot, asset="ada", window="5m", start=DAY, end=DAY)
    with pytest.raises(ValueError, match="unknown window '1h'"):
        await collect(gamma, data, spot, asset="btc", window="1h", start=DAY, end=DAY)


def test_loading_picks_the_days_asked_for(tmp_path: Path) -> None:
    for offset in range(3):
        day = date(2026, 10, 5 + offset)
        market = UpDownMarket(
            f"m{offset}", "c", day_start(day), day_start(day) + 300, 0, None, None, 0, 0
        )
        path = day_path(tmp_path, "btc", "5m", day)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            gzip.compress((json.dumps(market.to_dict()) + "\n\n").encode())
        )
    picked = load_markets(
        tmp_path, "btc", "5m", start=date(2026, 10, 6), end=date(2026, 10, 7)
    )
    assert [m.slug for m in picked] == ["m1"]
    assert len(list(load_markets(tmp_path, "btc", "5m"))) == 3
    assert load_spot(tmp_path, "BTCUSDT", DAY) is None
