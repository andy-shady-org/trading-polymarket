"""Unit tests for ``research/sports_gaps.py``: the listing-time recorder (FEAT-168).

Payload shapes follow Gamma's ``/markets/keyset`` moneyline markets, the
CLOB's ``/book`` and Kalshi's ``/events`` with nested markets on 2026-11-07
(a Gamers Club CS2 match and a W75 Brisbane ITF match, which Kalshi names by
surname)."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.http import HttpError, Response
from trading_polymarket.research import sports_gaps as sg
from trading_polymarket.tests.support.fakes import FakeTransport, Sequenced, fake_http

NOW = datetime(2026, 11, 7, 10, tzinfo=UTC).timestamp()
START = NOW + 6 * 3600


def iso(moment: float, sep: str = "T") -> str:
    return datetime.fromtimestamp(moment, UTC).strftime(f"%Y-%m-%d{sep}%H:%M:%SZ")


def pm_raw(slug: str = "cs2-reda-grmioe-2026-11-07", **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "slug": slug,
        "question": "Counter-Strike: RED Canids Academy vs Grêmio Esports (BO3)",
        "outcomes": json.dumps(["RED Canids Academy", "Grêmio Esports"]),
        "clobTokenIds": json.dumps([f"{slug}-0", f"{slug}-1"]),
        "createdAt": iso(NOW - 3600),
        "gameStartTime": datetime.fromtimestamp(START, UTC).strftime(
            "%Y-%m-%d %H:%M:%S+00"
        ),
        "feeSchedule": {"rate": 0.05, "exponent": 1, "takerOnly": True},
    }
    data.update(extra)
    return data


def k_market(ticker: str, label: str, bid: str = "0.4000", ask: str = "0.4200") -> dict:
    return {
        "ticker": ticker,
        "yes_sub_title": label,
        "created_time": iso(NOW - 7200),
        "occurrence_datetime": iso(START + 4 * 3600),
        "yes_bid_dollars": bid,
        "yes_bid_size_fp": "100.00",
        "yes_ask_dollars": ask,
        "yes_ask_size_fp": "50.00",
    }


def k_event(event: str = "KXCS2GAME-26NOV07GREMRED", **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "event_ticker": event,
        "title": "Gremio Esports vs. RED Canids Academy",
        "markets": [
            k_market(f"{event}-GRE", "Gremio Esports", "0.5500", "0.5700"),
            k_market(f"{event}-RED", "RED Canids Academy"),
        ],
    }
    data.update(extra)
    return data


def test_side_names_compare_by_their_words() -> None:
    assert sg.side_words("Team Grêmio Esports") == frozenset({"gremio"})
    assert sg.same_side("Bertrand", "Lea Bertrand")
    assert sg.same_side("Lea Bertrand", "Bertrand")
    assert not sg.same_side("Team", "Team Z") and not sg.same_side("Ivanov", "Beck")


def test_polymarket_matches_are_two_sided_tennis_or_esports_moneylines() -> None:
    match = sg.parse_pm(pm_raw())
    assert match is not None and match.sport == "esports" and match.league == "cs2"
    assert match.sides == ("RED Canids Academy", "Grêmio Esports")
    assert match.start == START and match.created == NOW - 3600
    assert match.fee.rate == 0.05
    assert match.listing(NOW)["venue"] == "polymarket"
    assert sg.parse_pm(pm_raw(slug="nba-lal-bos-2026-11-07")) is None
    assert sg.parse_pm(pm_raw(outcomes=json.dumps(["Yes", "No"]))) is None
    assert sg.parse_pm(pm_raw(outcomes="not json")) is None
    listed = sg.parse_pm(pm_raw(outcomes=["A", "B"]))  # a list, not a JSON string
    assert listed is not None and listed.sides == ("A", "B")
    assert sg.parse_pm(pm_raw(clobTokenIds=json.dumps(["one"]))) is None
    assert sg.parse_pm(pm_raw(gameStartTime=None)) is None
    no_fee = sg.parse_pm(pm_raw(feeSchedule=None))
    assert no_fee is not None and no_fee.fee.rate == 0.05  # never cheaper than live


def test_kalshi_matches_are_two_market_events_with_their_quotes() -> None:
    match = sg.parse_kalshi(k_event(), "KXCS2GAME")
    assert match is not None and match.sport == "esports"
    assert match.created == NOW - 7200 and match.start == START + 4 * 3600
    assert match.sides[0].quote == (0.55, 100.0, 0.57, 50.0)
    assert match.listing(NOW)["sides"] == ["Gremio Esports", "RED Canids Academy"]
    # 0 bid and 1 ask are empty sides.
    empty = k_market("T", "X", "0.0000", "1.0000")
    assert sg.kalshi_quote(empty) == (None, 100.0, None, 50.0)
    assert sg.parse_kalshi(k_event(), "KXNBAGAME") is None
    assert sg.parse_kalshi(k_event(markets=[k_market("T", "X")]), "KXCS2GAME") is None
    late = k_event(
        markets=[k_market("A", "A"), {**k_market("B", "B"), "created_time": None}]
    )
    assert sg.parse_kalshi(late, "KXCS2GAME") is None


def test_pairs_need_the_same_sport_close_starts_and_both_sides() -> None:
    pm = sg.parse_pm(pm_raw())
    kalshi = sg.parse_kalshi(k_event(), "KXCS2GAME")
    assert pm is not None and kalshi is not None
    assert sg.side_order(pm, kalshi) == (1, 0)
    far = sg.parse_kalshi(
        k_event(
            markets=[
                {**m, "occurrence_datetime": iso(START + 13 * 3600)}
                for m in k_event()["markets"]
            ]
        ),
        "KXCS2GAME",
    )
    assert far is not None and sg.side_order(pm, far) is None
    other = sg.parse_kalshi(
        k_event(markets=[k_market("A", "Gremio Esports"), k_market("B", "FURIA")]),
        "KXCS2GAME",
    )
    assert other is not None and sg.side_order(pm, other) is None
    tennis = sg.parse_kalshi(k_event(), "KXITFWMATCH")
    assert tennis is not None and sg.side_order(pm, tennis) is None
    pairs, ambiguous = sg.pair_up([pm], [kalshi])
    assert [p.order for p in pairs] == [(1, 0)] and ambiguous == 0
    row = pairs[0].row(NOW)
    assert row["kalshi_sides"] == ["RED Canids Academy", "Gremio Esports"]
    assert row["pair"] == f"{pm.slug}|{kalshi.event}" and row["pm_fee"]["rate"] == 0.05
    twin = sg.parse_kalshi(k_event("KXCS2GAME-TWIN"), "KXCS2GAME")
    assert twin is not None
    assert sg.pair_up([pm], [kalshi, twin]) == ([], 1)
    assert sg.pair_up([pm], [other]) == ([], 0)


def _venues(transport: FakeTransport) -> sg.Venues:
    http = fake_http(transport, max_retries=0)
    return sg.Venues(
        GammaClient(http), ClobClient(http), http, series={"KXCS2GAME": "esports"}
    )


def _transport(**routes: Any) -> FakeTransport:
    book = {
        "asset_id": "cs2-reda-grmioe-2026-11-07-0",
        "bids": [{"price": "0.42", "size": "30"}],
        "asks": [{"price": "0.44", "size": "20"}, {"price": "0.50", "size": "9"}],
    }
    transport = FakeTransport()
    transport.add(
        "/markets/keyset", routes.get("gamma", {"markets": [pm_raw(), pm_raw("nba-x")]})
    )
    transport.add("/book", routes.get("book", book))
    transport.add("/events", routes.get("kalshi", {"events": [k_event(), "odd"]}))
    return transport


async def test_a_cycle_writes_listings_pairs_and_quotes(tmp_path: Path) -> None:
    transport = _transport()
    recorder = sg.SportsRecorder(
        _venues(transport), sg.SportsWriter(tmp_path), clock=lambda: NOW
    )
    assert await recorder.cycle() == 1
    assert await recorder.cycle() == 1  # listings and pairs are written once
    day = tmp_path / "2026-11-07"
    listings = [json.loads(line) for line in (day / "listings.jsonl").open()]
    assert [r["venue"] for r in listings] == ["polymarket", "kalshi"]
    (pair,) = [json.loads(line) for line in (day / "pairs.jsonl").open()]
    assert pair["kalshi_tickers"][0].endswith("-RED")
    with gzip.open(day / "quotes.jsonl.gz", "rt") as handle:
        rows = [json.loads(line) for line in handle]
    assert rows[0] == [
        NOW,
        pair["pair"],
        0.42,
        30.0,
        0.44,
        20.0,
        0.4,
        100.0,
        0.42,
        50.0,
        0.55,
        100.0,
        0.57,
        50.0,
    ]
    assert recorder.writer.counts == {"listings": 2, "pairs": 1, "quotes": 2}
    keyset = next(u for u in transport.calls if "/markets/keyset" in u)
    assert "sports_market_types=moneyline" in keyset and "ascending=false" in keyset
    kalshi = next(u for u in transport.calls if "/events" in u)
    assert "series_ticker=KXCS2GAME" in kalshi and "status=open" in kalshi


async def test_a_book_that_is_gone_is_a_row_of_nulls(tmp_path: Path) -> None:
    transport = _transport(book=Response(404, b"{}"))
    recorder = sg.SportsRecorder(
        _venues(transport), sg.SportsWriter(tmp_path), clock=lambda: NOW
    )
    await recorder.cycle()
    with gzip.open(tmp_path / "2026-11-07" / "quotes.jsonl.gz", "rt") as handle:
        (row,) = [json.loads(line) for line in handle]
    assert row[2:6] == [None, None, None, None]
    empty = _transport(book={"bids": [], "asks": []}, kalshi={"events": None})
    recorder = sg.SportsRecorder(_venues(empty), sg.SportsWriter(tmp_path / "x"))
    assert await recorder.cycle() == 0  # no Kalshi events: no pair


async def test_pairs_past_their_window_are_retired_and_not_taken_back(
    tmp_path: Path,
) -> None:
    now = [NOW]
    recorder = sg.SportsRecorder(
        _venues(_transport()), sg.SportsWriter(tmp_path), clock=lambda: now[0]
    )
    await recorder.cycle()
    late = START + sg.RECORD_AFTER_START_SECONDS + 1
    recorder.retire(late)
    assert recorder.pairs == {}
    now[0] = late
    assert await recorder.cycle() == 0 and recorder.pairs == {}
    assert recorder.writer.counts["pairs"] == 1


async def test_record_runs_cycles_until_the_hours_pass_and_survives_errors(
    tmp_path: Path,
) -> None:
    clock = [NOW]
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    transport = _transport(
        gamma=Sequenced(HttpError("down", status=503), {"markets": [pm_raw()]})
    )
    logged: list[str] = []
    counts = await sg.record(
        _venues(transport),
        directory=tmp_path,
        hours=0.1,
        interval=120.0,
        clock=lambda: clock[0],
        sleep=sleep,
        log=logged.append,
    )
    assert logged[0].startswith("cycle failed (1 so far)")
    assert "1 pairs, 1 quotes, 0 ambiguous, 2 listings" in logged[1]
    assert counts["quotes"] == len(logged) - 1 and sleeps[0] == 120.0


def test_writer_skips_empty_batches(tmp_path: Path) -> None:
    writer = sg.SportsWriter(tmp_path)
    writer.rows(NOW, "listings", [])
    writer.quotes(NOW, [])
    assert not tmp_path.joinpath("2026-11-07").exists() and writer.counts == {}


@pytest.mark.parametrize("league", sorted(sg.PM_LEAGUES))
def test_every_league_is_tennis_or_esports(league: str) -> None:
    assert sg.PM_LEAGUES[league] in {"tennis", "esports"}
    assert set(sg.KALSHI_SERIES.values()) == {"tennis", "esports"}
