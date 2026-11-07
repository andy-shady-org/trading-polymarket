"""Unit tests for ``research/sports_gaps_report.py``: gaps after listing (FEAT-168)."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.fees import FeeSchedule
from trading_polymarket.research import sports_gaps_report as sr
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http

NOW = datetime(2026, 11, 7, 10, tzinfo=UTC).timestamp()
FEE = FeeSchedule(rate=0.05)
KEY = "itf-ivanov-beck|KXITFWMATCH-26NOV07IVABEC"


def pair_row(**extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "pair": KEY,
        "sport": "tennis",
        "pm_slug": "itf-ivanov-beck",
        "pm_fee": {"rate": 0.05, "exponent": 1},
        "pm_created": NOW - 1800,
        "kalshi_created": NOW - 600,
        "start": NOW + 6 * 3600,
    }
    data.update(extra)
    return data


INFO = sr.PairInfo.from_row(pair_row())


def quote(
    rx: float,
    pm: tuple[Any, Any, Any, Any] = (0.40, 50.0, 0.42, 50.0),
    k0: tuple[Any, Any, Any, Any] = (0.46, 10.0, 0.48, 10.0),
    k1: tuple[Any, Any, Any, Any] = (0.52, 10.0, 0.54, 10.0),
) -> list[Any]:
    return [rx, KEY, *pm, *k0, *k1]


def test_side_views_mirror_the_first_outcome_book() -> None:
    row = quote(NOW)
    assert sr.side_view(row, 0) == (0.42, 50.0, 0.46, 0.48)
    ask, size, k_bid, k_ask = sr.side_view(row, 1)
    assert ask == pytest.approx(0.60) and (size, k_bid, k_ask) == (50.0, 0.52, 0.54)
    assert sr.side_view(quote(NOW, pm=(None, None, 0.4, 1.0)), 1)[0] is None


def test_a_gap_is_the_ask_with_its_fee_well_below_kalshi() -> None:
    # 0.42 + 0.05 × 0.42 × 0.58 = 0.4322; Kalshi mid 0.47: edge 0.0378.
    gap = sr.gap_at(quote(NOW), 0, FEE, sr.PRIMARY)
    assert gap is not None and gap.cost == pytest.approx(0.43218)
    assert gap.edge == pytest.approx(0.03782) and gap.notional == pytest.approx(21.0)
    assert sr.gap_at(quote(NOW), 1, FEE, sr.PRIMARY) is None  # 0.60 vs 0.53
    wide = quote(NOW, k0=(0.40, 1.0, 0.50, 1.0))
    assert sr.gap_at(wide, 0, FEE, sr.PRIMARY) is None
    small = quote(NOW, pm=(0.40, 50.0, 0.42, 5.0))
    assert sr.gap_at(small, 0, FEE, sr.PRIMARY) is None
    assert sr.gap_at(quote(NOW, k0=(None, 0, None, 0)), 0, FEE, sr.PRIMARY) is None
    assert sr.gap_at(quote(NOW, pm=(0.4, 1.0, 0.0, 9.0)), 0, FEE, sr.PRIMARY) is None
    assert sr.gap_at(quote(NOW), 0, FEE, sr.GapRule(gap=0.05)) is None


def test_consecutive_gap_snapshots_are_one_event() -> None:
    gone = quote(NOW + 360, k0=(0.40, 1.0, 0.42, 1.0))
    rows = [quote(NOW), quote(NOW + 120), quote(NOW + 240), gone, quote(NOW + 480)]
    first, second = sr.side_events(INFO, rows, 0, sr.PRIMARY)
    assert (first.snapshots, first.first_rx, first.last_rx) == (3, NOW, NOW + 240)
    assert first.hours_after_listing == pytest.approx(600 / 3600)
    assert first.hours_before_start == pytest.approx(6.0)
    assert first.pm_listed_first is True and second.first_rx == NOW + 480
    assert first.net_per_dollar is None


def test_events_by_pair_ignore_unknown_pairs_and_order_by_time() -> None:
    other = sr.PairInfo.from_row(pair_row(pair="b|K2", pm_slug="b"))
    rows = [quote(NOW + 120), quote(NOW), ["NOW", "unknown", *([None] * 12)]]
    rows.append([NOW - 60, "b|K2", *quote(NOW)[2:]])
    events = sr.find_events({KEY: INFO, "b|K2": other}, rows)
    assert [(e.pair, e.first_rx) for e in events] == [("b|K2", NOW - 60), (KEY, NOW)]
    assert events[1].snapshots == 2


def test_settlement_and_net_per_dollar() -> None:
    assert sr.winner_of({"outcomePrices": json.dumps(["0", "1"])}) == 1
    assert sr.winner_of({"outcomePrices": json.dumps(["0.5", "0.5"])}) is None
    assert sr.winner_of({"outcomePrices": "bad"}) is None
    events = sr.side_events(INFO, [quote(NOW)], 0, sr.PRIMARY)
    other = sr.PairInfo.from_row(pair_row(pm_slug="other"))
    events += sr.side_events(other, [quote(NOW)], 0, sr.PRIMARY)
    unsettled = sr.side_events(
        sr.PairInfo.from_row(pair_row(pm_slug="u")), [quote(NOW)], 0, sr.PRIMARY
    )
    sr.settle([*events, *unsettled], {"itf-ivanov-beck": 0, "other": 1})
    assert unsettled[0].won is None
    assert events[0].won is True and events[1].won is False
    assert events[0].net_per_dollar == pytest.approx((1 - 0.43218) / 0.43218)
    assert events[1].net_per_dollar == pytest.approx(-1.0)
    assert events[0].to_dict()["net_per_dollar"] == events[0].net_per_dollar


async def test_winners_come_from_gammas_closed_markets() -> None:
    transport = FakeTransport().add(
        "/markets",
        [
            {"slug": "a", "outcomePrices": json.dumps(["1", "0"])},
            {"slug": "b", "outcomePrices": json.dumps(["0.4", "0.6"])},
        ],
    )
    gamma = GammaClient(fake_http(transport))
    assert await sr.fetch_winners(gamma, ["b", "a", "a"]) == {"a": 0}
    assert "closed=true" in transport.calls[0]


def _event(rx: float, won: bool | None, *, hours: float = 0.5) -> sr.Event:
    (event,) = sr.side_events(INFO, [quote(rx)], 0, sr.PRIMARY)
    event.won, event.hours_after_listing = won, hours
    return event


def test_the_summary_counts_by_sport_and_listing_age_with_halves() -> None:
    events = [
        _event(NOW, True),
        _event(NOW + 10, False, hours=2.0),
        _event(NOW + 100, True, hours=20.0),
        _event(NOW + 200, None, hours=5.0),
    ]
    summary = sr.summarize(events, NOW + 50)
    assert summary["events"] == 4 and summary["matches"] == 1
    assert summary["by_sport"] == {"tennis": 4}
    assert summary["by_hours_after_listing"] == {
        "0-1 h": 1,
        "1-3 h": 1,
        "3-12 h": 1,
        "12 h+": 1,
    }
    assert summary["settled"] == 3 and summary["won"] == 2
    first, second = summary["net_per_dollar_halves"]
    assert first == pytest.approx(((1 - 0.43218) / 0.43218 - 1.0) / 2)
    assert second == pytest.approx((1 - 0.43218) / 0.43218)
    empty = sr.summarize([], NOW)
    assert empty["median_edge"] is None and empty["net_per_dollar"] is None


def _summary(**extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "events": 40,
        "matches": 20,
        "settled": 35,
        "net_per_dollar_halves": [0.05, 0.02],
        "median_notional": 30.0,
    }
    data.update(extra)
    return data


def test_the_decision_follows_the_run_record() -> None:
    assert sr.decision(6, _summary()) == "too early: 6 of at least 7 days"
    assert sr.decision(14, _summary()) == "GO"
    assert sr.decision(14, _summary(events=29)) == "EXTEND"
    assert sr.decision(14, _summary(matches=14)) == "EXTEND"
    assert sr.decision(14, _summary(settled=10)) == "EXTEND"
    assert sr.decision(28, _summary(events=3)) == "NO-GO: too few gaps"
    halves = _summary(net_per_dollar_halves=[0.1, -0.01])
    assert sr.decision(14, halves) == "NO-GO: not positive in both halves"
    assert sr.decision(14, _summary(net_per_dollar_halves=[0.1, None])).startswith(
        "NO-GO"
    )
    small = _summary(median_notional=10.0)
    assert sr.decision(14, small) == "NO-GO: too little offered at the gap"


def test_a_recording_loads_from_its_day_folders(tmp_path: Path) -> None:
    day = tmp_path / "2026-11-07"
    day.mkdir()
    (day / "pairs.jsonl").write_text(json.dumps(pair_row()) + "\n\n")
    (day / "listings.jsonl").write_text('{"venue": "kalshi"}\n{"venue": "x"}\n')
    with gzip.open(day / "quotes.jsonl.gz", "at") as handle:
        handle.write(json.dumps(quote(NOW)) + "\n")
    (tmp_path / "2026-11-08").mkdir()
    (tmp_path / "notes").mkdir()
    recording = sr.load_recording(tmp_path)
    assert recording.days == ["2026-11-07", "2026-11-08"]
    assert list(recording.pairs) == [KEY] and recording.listings == 2
    assert recording.quotes == [quote(NOW)]
    assert sr.load_recording(tmp_path / "missing").days == []
