from __future__ import annotations

import json

import pytest

from trading_polymarket.clients.kalshi import KalshiEvent, KalshiMarket
from trading_polymarket.markets import markets_from_event
from trading_polymarket.pairs import (
    FED_SERIES,
    SIDE_NO,
    SIDE_YES,
    SOURCE_APPROVED,
    SOURCE_FED,
    Reference,
    VenuePair,
    fed_code_kalshi,
    fed_code_polymarket,
    is_fed_decision_event,
    load_pairs,
    match_fed,
    save_pairs,
)
from trading_polymarket.tests.support.factories import (
    FED_BUCKETS,
    FED_MEETING,
    fed_kalshi_event,
    fed_no,
    fed_pm_event,
    fed_yes,
    kalshi_market,
)


def pm(raw: dict) -> tuple[dict, list]:
    return raw, markets_from_event(raw)


def test_pair_validation_and_round_trip() -> None:
    pair = VenuePair("tok", "KXFEDDECISION-26NOV-H0", SIDE_NO, label="x")
    assert pair.series == FED_SERIES and pair.source == SOURCE_APPROVED
    assert VenuePair.from_dict(pair.to_dict()) == pair
    assert VenuePair("t", "K-1", kalshi_series="S").series == "S"
    minimal = VenuePair.from_dict({"pm_token": 1, "kalshi_ticker": "K"})
    assert minimal.kalshi_side == SIDE_YES and minimal.label == ""
    with pytest.raises(ValueError):
        VenuePair("t", "K", "maybe")
    with pytest.raises(ValueError):
        VenuePair("", "K")


def test_reference_of_each_side() -> None:
    market = KalshiMarket.from_api(kalshi_market())
    yes = Reference.of(market, SIDE_YES, 5.0)
    assert (yes.bid, yes.ask, yes.volume_24h, yes.timestamp) == (0.6, 0.62, 25000, 5.0)
    assert yes.mid == pytest.approx(0.61) and yes.spread == pytest.approx(0.02)
    no = Reference.of(market, SIDE_NO, 5.0)
    assert (no.bid, no.ask) == (0.38, 0.4)
    empty = KalshiMarket.from_api(
        kalshi_market(yes_bid_dollars="0", yes_ask_dollars="1")
    )
    for side in (SIDE_YES, SIDE_NO):
        ref = Reference.of(empty, side, 0)
        assert ref.mid is None and ref.spread is None


@pytest.mark.parametrize(
    ("label", "code"),
    [
        ("No change", "H0"),
        ("no change in rates", "H0"),
        ("25 bps decrease", "C25"),
        ("50+ bps decrease", "C26"),
        ("25 bps increase", "H25"),
        ("50+ bps increase", "H26"),
        ("50 bps decrease", None),
        ("75+ bps decrease", None),
        ("Something else", None),
    ],
)
def test_fed_code_polymarket(label: str, code: str | None) -> None:
    assert fed_code_polymarket(label) == code


@pytest.mark.parametrize(
    ("label", "code"),
    [
        ("Fed maintains rate", "H0"),
        ("No change", "H0"),
        ("Cut 25bps", "C25"),
        ("Cut >25bps", "C26"),
        ("Hike 25bps", "H25"),
        ("Hike >25bps", "H26"),
        ("Cut 50bps", None),
        ("Other", None),
    ],
)
def test_fed_code_kalshi(label: str, code: str | None) -> None:
    assert fed_code_kalshi(label) == code


def test_every_bucket_maps_to_the_same_code_on_both_venues() -> None:
    for pm_label, kalshi_label, code in FED_BUCKETS:
        assert fed_code_polymarket(pm_label) == fed_code_kalshi(kalshi_label) == code


def test_is_fed_decision_event() -> None:
    assert is_fed_decision_event("Fed Decision in December?")
    assert is_fed_decision_event(" fed decision in March ")
    assert not is_fed_decision_event("Fed Decision in December? (Powell speech)")
    assert not is_fed_decision_event("How many Fed cuts in 2026?")


def test_match_fed_pairs_both_tokens_of_each_bucket() -> None:
    kalshi = [KalshiEvent.from_api(fed_kalshi_event())]
    pairs = match_fed([pm(fed_pm_event())], kalshi)
    assert len(pairs) == 10
    by_token = {p.pm_token: p for p in pairs}
    hold_yes = by_token[fed_yes("No change")]
    assert hold_yes.kalshi_ticker == "KXFEDDECISION-26NOV-H0"
    assert hold_yes.kalshi_side == SIDE_YES and hold_yes.source == SOURCE_FED
    assert hold_yes.label == "Fed Nov 2026 No change"
    hold_no = by_token[fed_no("No change")]
    assert hold_no.kalshi_side == SIDE_NO and hold_no.label.endswith("(No)")
    assert by_token[fed_yes("50+ bps increase")].kalshi_ticker.endswith("-H26")


def test_match_fed_skips_what_cannot_be_matched() -> None:
    kalshi = [KalshiEvent.from_api(fed_kalshi_event())]
    other = fed_pm_event(title="How many Fed cuts in 2026?")
    far = fed_pm_event(meeting=FED_MEETING + 30 * 86400)
    no_dates = fed_pm_event()
    for raw in no_dates["markets"]:
        raw["endDate"] = None
    odd = fed_pm_event()
    odd["markets"][0]["groupItemTitle"] = "75 bps decrease"
    assert match_fed([pm(other), pm(far), pm(no_dates)], kalshi) == []
    assert len(match_fed([pm(odd)], kalshi)) == 8
    # Kalshi events without close times, and the nearer of two candidates
    undated = fed_kalshi_event()
    for raw in undated["markets"]:
        raw["close_time"] = None
    later = fed_kalshi_event(meeting=FED_MEETING + 2 * 86400)
    later["event_ticker"] = "LATER"
    for raw in later["markets"]:
        raw["ticker"] = raw["ticker"].replace("26NOV", "LATER")
    events = [KalshiEvent.from_api(e) for e in (undated, later, fed_kalshi_event())]
    pairs = match_fed([pm(fed_pm_event())], events)
    assert {p.kalshi_ticker.split("-")[1] for p in pairs} == {"26NOV"}
    assert match_fed([pm(fed_pm_event())], [KalshiEvent.from_api(undated)]) == []


def test_load_and_save_pairs(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "sub" / "pairs.json"
    assert load_pairs(path) == []
    a = VenuePair("t1", "K-1")
    b = VenuePair("t2", "K-2", SIDE_NO)
    assert save_pairs([a, b, a], path) == str(path)
    assert load_pairs(path) == [a, b]
    path.write_text(
        json.dumps(
            [a.to_dict(), {"pm_token": "x"}, {"pm_token": "", "kalshi_ticker": "K"}, 7]
        )
    )
    assert load_pairs(path) == [a]
    path.write_text(json.dumps({"not": "a list"}))
    assert load_pairs(path) == []
