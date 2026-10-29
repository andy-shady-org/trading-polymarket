from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.http import Response
from trading_polymarket.clients.kalshi import Candle, KalshiClient
from trading_polymarket.config import FedLane
from trading_polymarket.research import fed
from trading_polymarket.research.fed import FedBucket, FedMeeting
from trading_polymarket.research.records import read_jsonl
from trading_polymarket.tests.support.factories import (
    FED_MEETING,
    fed_kalshi_event,
    fed_pm_event,
    fed_yes,
)
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http

C = FED_MEETING - 3600  # Kalshi's close
H = 3600.0
LANE = FedLane(enabled=True)


def candles(
    hours: range,
    bid: float | None = 0.60,
    ask: float | None = 0.62,
    volume: float = 1000.0,
) -> tuple[Candle, ...]:
    return tuple(Candle(C - h * H, bid, ask, volume) for h in hours)


def bucket(
    pm: list[tuple[float, float]] | None = None,
    kalshi: tuple[Candle, ...] | None = None,
    **kw: Any,
) -> FedBucket:
    base: dict[str, Any] = {
        "bucket": "No change",
        "code": "H0",
        "yes_token": "Y" * 20,
        "no_token": "N" * 20,
        "kalshi_ticker": "KXFEDDECISION-26NOV-H0",
        "won": True,
        "kalshi_won": True,
        "pm": tuple(pm if pm is not None else [(C - 10 * H, 0.55), (C - 5 * H, 0.62)]),
        "kalshi": kalshi if kalshi is not None else candles(range(10, -2, -1)),
    }
    base.update(kw)
    return FedBucket(**base)


def meeting(*buckets: FedBucket, **kw: Any) -> FedMeeting:
    base: dict[str, Any] = {
        "event_id": "1",
        "title": "Fed Decision in November?",
        "kalshi_event": "KXFEDDECISION-26NOV",
        "close_time": C,
        "buckets": buckets or (bucket(),),
    }
    base.update(kw)
    return FedMeeting(**base)


def sells(result: Any) -> list[dict]:
    return [r["payload"] for r in result.records if r["payload"]["action"] == "sell"]


def test_bucket_helpers_and_round_trip(tmp_path: Path) -> None:
    b = bucket()
    assert b.pm_price(C - 11 * H) is None and b.pm_price(C - 6 * H) == 0.55
    assert b.reference_volume(C - 10 * H) == 1000.0
    assert b.reference_volume(C) == 11000.0 and b.reference_volume(C, hours=2) == 2000.0
    m = meeting(b, bucket(kalshi_won=None))
    assert m.agreed
    assert not meeting(bucket(kalshi_won=False)).agreed
    path = tmp_path / "fed.jsonl"
    path.write_text(json.dumps(m.to_dict()) + "\n")
    loaded = fed.load_meetings(path)
    assert loaded[0].buckets[0].kalshi[0] == b.kalshi[0]
    assert loaded[0].buckets[1].kalshi_won is None
    assert loaded == [m]


def test_buys_below_kalshi_and_sells_on_convergence() -> None:
    result = fed.backtest_fed([meeting()], LANE)
    assert result.trades == 1 and result.markets == 1
    sale = sells(result)[0]
    assert sale["exit_reason"] == fed.EXIT_CONVERGED if "exit_reason" in sale else True
    assert result.net == pytest.approx(25 / 0.56 * 0.61 - 25, abs=1e-3)
    buy = result.records[0]["payload"]
    assert buy["strategy"] == "fed"
    held = fed.backtest_fed([meeting()], FedLane(exit_on_convergence=False))
    assert held.net == pytest.approx(25 / 0.56 - 25, abs=1e-3)


def test_the_no_side_trades_against_one_minus_kalshi() -> None:
    # Kalshi Yes 0.60/0.62 -> No 0.38/0.40 (mid 0.39); Polymarket No 1 - 0.68 = 0.32.
    b = bucket(pm=[(C - 10 * H, 0.68)], won=False, kalshi_won=False)
    result = fed.backtest_fed([meeting(b)], LANE)
    assert result.trades == 1
    assert result.records[0]["payload"]["instrument_id"] == "N" * 20
    notional = 0.25 * (0.39 - 0.33) / (1 - 0.33) * 1000  # quarter Kelly < cap
    assert result.net == pytest.approx(notional / 0.33 - notional, abs=1e-3)


def test_fees_are_charged_on_entry_and_on_a_converged_exit() -> None:
    free = fed.backtest_fed([meeting()], LANE).net
    paid = fed.backtest_fed([meeting(bucket(fee_rate=0.02))], LANE).net
    assert paid < free


@pytest.mark.parametrize(
    "item",
    [
        bucket(pm=[]),  # no Polymarket price
        bucket(kalshi=candles(range(10, -2, -1), bid=0.50, ask=0.62)),  # wide
        bucket(kalshi=candles(range(10, -2, -1), volume=0.0)),  # no volume
        bucket(pm=[(C - 10 * H, 0.60)]),  # no edge
        bucket(pm=[(C - 10 * H, 0.40)]),  # gap above max_edge
        bucket(pm=[(C - 10 * H, 0.01)], kalshi=candles(range(10, 0, -1), 0.02, 0.03)),
        bucket(pm=[(C - 0.5 * H, 0.55)]),  # only inside min_hours
        bucket(
            kalshi=(
                *candles(range(10, 0, -1), bid=0.5, ask=0.6),
                Candle(C + H, 0.6, 0.62, 1e4),
            )
        ),
    ],
)
def test_no_trade(item: FedBucket) -> None:
    assert fed.backtest_fed([meeting(item)], LANE).trades == 0


def test_kelly_below_min_notional_does_not_trade() -> None:
    lane = FedLane(enabled=True, min_notional=50.0, max_notional=60.0)
    assert fed.backtest_fed([meeting()], lane).trades == 0


def test_a_missing_reference_mid_holds_to_resolution() -> None:
    later = (*candles(range(10, 5, -1)), *candles(range(5, -1, -1), bid=None))
    result = fed.backtest_fed([meeting(bucket(kalshi=later))], LANE)
    assert result.trades == 1 and sells(result)[0]["price"] == 1.0


def test_disagreeing_meetings_are_skipped_and_counted() -> None:
    result = fed.backtest_fed(
        [meeting(), meeting(bucket(kalshi_won=False), event_id="2")], LANE
    )
    assert result.markets == 1 and result.scores["disagreements"] == 1
    assert "disagreements" not in fed.backtest_fed([meeting()], LANE).scores


def test_score_horizons() -> None:
    scores = fed.score_horizons([meeting()], horizons=(1.0, 6.0, 100.0))
    one = scores["1h"]
    assert one["buckets"] == 1
    assert one["market"] == pytest.approx((0.62 - 1) ** 2, abs=1e-4)
    assert one["model"] == pytest.approx((0.61 - 1) ** 2, abs=1e-4)
    assert one["mean_abs_gap"] == pytest.approx(0.01, abs=1e-4)
    assert "6h" in scores and "100h" not in scores
    one_sided = bucket(kalshi=candles(range(10, -2, -1), bid=None))
    assert fed.score_horizons([meeting(one_sided)]) == {}


# -- collection ----------------------------------------------------------------
def settled_pm(meeting_time: float, title: str, winner: str, event_id: str) -> dict:
    raw = fed_pm_event(meeting=meeting_time, title=title)
    raw["id"] = event_id
    for market in raw["markets"]:
        won = market["groupItemTitle"] == winner
        market.update(
            closed=True,
            acceptingOrders=False,
            outcomePrices=json.dumps(["1", "0"] if won else ["0", "1"]),
        )
    return raw


def kalshi_settled(meeting_time: float, ticker: str, winner: str) -> dict:
    raw = fed_kalshi_event(meeting=meeting_time)
    raw["event_ticker"] = ticker
    for market in raw["markets"]:
        market["ticker"] = f"{ticker}-{market['ticker'].rsplit('-', 1)[1]}"
        market["result"] = "yes" if market["ticker"].endswith(winner) else "no"
    return raw


SEPT = FED_MEETING - 50 * 86400


def candle_payload(close: float, close_key: str = "close_dollars") -> dict:
    return {
        "candlesticks": [
            {
                "end_period_ts": close - h * H,
                "yes_bid": {close_key: "0.60"},
                "yes_ask": {close_key: "0.62"},
                "volume_fp": "100",
            }
            for h in range(3, 0, -1)
        ]
    }


def collect_routes(**extra: Any) -> FakeTransport:
    archived = kalshi_settled(SEPT, "KXFEDDECISION-26SEP", "H25")
    archived_markets = archived.pop("markets")
    table: dict[str, Any] = {
        "/public-search": {
            "events": [
                settled_pm(FED_MEETING, "Fed Decision in November?", "No change", "11"),
                settled_pm(SEPT, "Fed Decision in September?", "25 bps increase", "9"),
                fed_pm_event(title="Fed Decision in December?"),  # still open
                settled_pm(
                    SEPT - 90 * 86400, "Fed Decision in June?", "No change", "6"
                ),
                settled_pm(FED_MEETING, "How many cuts?", "No change", "5"),
            ]
        },
        "/events?": {
            "events": [
                kalshi_settled(FED_MEETING, "KXFEDDECISION-26NOV", "H0"),
                archived,
                {"event_ticker": "KXFEDDECISION-23JAN", "markets": []},
            ]
        },
        "/historical/markets?event_ticker=KXFEDDECISION-26SEP": {
            "markets": archived_markets
        },
        "/historical/markets?": {"markets": []},
        "/historical/markets/": candle_payload(SEPT - H, close_key="close"),
        "/series/KXFEDDECISION/markets/": candle_payload(C),
        "/prices-history": {"history": [{"t": C - 2 * H, "p": 0.55}]},
    }
    table.update(extra)
    return FakeTransport(table)


def clients(transport: FakeTransport) -> tuple[GammaClient, ClobClient, KalshiClient]:
    http = fake_http(transport, max_retries=0)
    return GammaClient(http), ClobClient(http), KalshiClient(http)


async def test_collect_fed_stores_matched_settled_meetings(tmp_path: Path) -> None:
    transport = collect_routes()
    path = tmp_path / "fed.jsonl"
    lines: list[str] = []
    written = await fed.collect_fed(
        *clients(transport), path=path, days=1.0, progress=lines.append
    )
    assert written == 2
    rows = list(read_jsonl(path))
    assert [r["kalshi_event"] for r in rows] == [
        "KXFEDDECISION-26NOV",
        "KXFEDDECISION-26SEP",
    ]
    nov = FedMeeting.from_dict(rows[0])
    assert nov.close_time == C and len(nov.buckets) == 5 and nov.agreed
    hold = next(b for b in nov.buckets if b.code == "H0")
    assert hold.yes_token == fed_yes("No change") and hold.won and hold.kalshi_won
    assert hold.pm == ((C - 2 * H, 0.55),) and hold.kalshi[0].volume == 100.0
    sept = FedMeeting.from_dict(rows[1])
    assert next(b for b in sept.buckets if b.code == "H25").won
    assert sept.buckets[0].kalshi[0].yes_bid == 0.60  # archived "close" keys
    assert any("no Kalshi meeting" in line for line in lines)
    # 7-day chunks: one window of a day each
    assert transport.count("/prices-history") == 10
    again = await fed.collect_fed(*clients(transport), path=path, days=1.0)
    assert again == 0


async def test_long_windows_are_fetched_in_chunks(tmp_path: Path) -> None:
    transport = collect_routes()
    await fed.collect_fed(*clients(transport), path=tmp_path / "f.jsonl", days=10.0)
    assert transport.count("/prices-history") == 20


async def test_a_market_archived_mid_collection_falls_back(tmp_path: Path) -> None:
    transport = collect_routes()
    transport.routes["/series/KXFEDDECISION/markets/"] = _status(404)
    written = await fed.collect_fed(*clients(transport), path=tmp_path / "f.jsonl")
    assert written == 2
    assert transport.count("/historical/markets/") == 10


async def test_errors_skip_the_meeting(tmp_path: Path) -> None:
    transport = collect_routes()
    transport.routes["/series/KXFEDDECISION/markets/"] = _status(500)
    lines: list[str] = []
    written = await fed.collect_fed(
        *clients(transport), path=tmp_path / "f.jsonl", progress=lines.append
    )
    assert written == 1 and any("HTTP 500" in line for line in lines)
    quiet = collect_routes()
    quiet.routes["/prices-history"] = _status(500)
    assert await fed.collect_fed(*clients(quiet), path=tmp_path / "g.jsonl") == 0


def _status(code: int) -> Response:
    return Response(code, b"{}")
