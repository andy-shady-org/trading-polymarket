from __future__ import annotations

from typing import Any

import pytest

from trading_polymarket.book import Level, OrderBook
from trading_polymarket.markets import Market
from trading_polymarket.research.arb import (
    DEPTHS,
    KIND_NO,
    KIND_YES,
    SetSpec,
    cost_of,
    event_sets,
    ladder,
    leg_levels,
    live_markets,
    quote,
    steps,
)
from trading_polymarket.tests.support.factories import gamma_market, market

FREE = {"feeSchedule": None, "feesEnabled": False}


def leg(i: int, **extra: Any) -> Market:
    return market(id=str(i), yes=f"y{i}", no=f"n{i}", negRisk=True, **{**FREE, **extra})


def raw_leg(i: int, **extra: Any) -> dict[str, Any]:
    return gamma_market(
        id=str(i), yes=f"y{i}", no=f"n{i}", negRisk=True, **{**FREE, **extra}
    )


def spec(kind: str, markets: tuple[Market, ...], augmented: bool = False) -> SetSpec:
    return SetSpec(
        kind, "e1", "who-wins", "Who wins?", ("politics",), augmented, markets
    )


def book(token: str, bids=(), asks=(), **extra: Any) -> OrderBook:
    return OrderBook.from_levels(token, bids, asks, **extra)


def test_set_spec_key_payout_tokens_and_row() -> None:
    legs = (leg(1), leg(2), leg(3, feeSchedule={"rate": 0.05}, feesEnabled=True))
    yes, no = spec(KIND_YES, legs), spec(KIND_NO, legs)
    assert yes.key == "e1:yes_set" and no.key == "e1:no_set"
    assert yes.payout == 1.0 and no.payout == 2.0
    assert yes.tokens == ("y1", "y2", "y3")
    row = no.row()
    assert row["legs"] == 3 and row["payout"] == 2.0 and row["fee_legs"] == 1
    assert row["tags"] == ["politics"] and row["tokens"] == ["y1", "y2", "y3"]
    assert row["resolves"] == max(m.end_time or 0 for m in legs)
    assert spec(KIND_YES, (leg(1, endDate=None),)).resolves is None


@pytest.mark.regression("TP-13")
def test_a_live_outcome_that_cannot_be_bought_leaves_no_full_set() -> None:
    open_ = [leg(1), leg(2)]
    assert live_markets(2, open_, augmented=False) == tuple(open_)
    paused = leg(3, acceptingOrders=False)
    assert live_markets(3, [*open_, paused], augmented=False) is None
    pending = leg(3, closed=True, acceptingOrders=False, prices=["0.5", "0.5"])
    assert live_markets(3, [*open_, pending], augmented=False) is None
    # an outcome that could not be parsed is still an outcome
    assert live_markets(3, open_, augmented=False) is None


def test_resolved_no_outcomes_are_left_out_and_a_yes_decides_the_event() -> None:
    open_ = [leg(1), leg(2)]
    lost = leg(3, closed=True, acceptingOrders=False, prices=["0", "1"])
    won = leg(4, closed=True, acceptingOrders=False, prices=["1", "0"])
    assert live_markets(3, [*open_, lost], augmented=False) == tuple(open_)
    assert live_markets(3, [*open_, won], augmented=False) is None
    assert live_markets(2, [leg(1), lost], augmented=False) is None  # one left


def test_unlisted_placeholders_count_only_in_augmented_events() -> None:
    open_ = [leg(1), leg(2)]
    placeholder = leg(3, active=False)
    assert live_markets(3, [*open_, placeholder], augmented=True) == tuple(open_)
    assert live_markets(3, [*open_, placeholder], augmented=False) is None
    plain = market(id="9", yes="y9", no="n9", negRisk=False)
    assert live_markets(3, [*open_, plain], augmented=False) is None


def test_event_sets_builds_both_sets_or_none() -> None:
    event: dict[str, Any] = {
        "id": "e1",
        "slug": "who-wins",
        "title": "Who wins?",
        "negRisk": True,
        "negRiskAugmented": True,
        "tags": [{"slug": "politics"}],
        "markets": [raw_leg(1), raw_leg(2), raw_leg(3, negRiskOther=True), "junk"],
    }
    found = event_sets(event)
    assert [s.kind for s in found] == [KIND_YES, KIND_NO]
    assert found[0].augmented and found[0].tags == ("politics",)
    assert found[1].payout == 2.0 and found[0].title == "Who wins?"
    assert event_sets({**event, "negRisk": False}) == []
    assert event_sets({**event, "markets": [raw_leg(1)]}) == []
    given = event_sets(event, [leg(1), leg(2), leg(3)])
    assert given[0].markets[0].event_id == ""  # the given markets are used


@pytest.mark.regression("TP-13")
def test_an_augmented_event_has_no_full_set_until_other_can_be_bought() -> None:
    other = raw_leg(3, negRiskOther=True, active=False, acceptingOrders=False)
    placeholder = raw_leg(4, active=False, acceptingOrders=False)
    event = {
        "id": "e2",
        "negRisk": True,
        "negRiskAugmented": True,
        "markets": [raw_leg(1), raw_leg(2), other, placeholder],
    }
    assert event_sets(event) == []
    live_other = raw_leg(3, negRiskOther=True)
    found = event_sets({**event, "markets": [raw_leg(1), raw_leg(2), live_other]})
    assert len(found) == 2 and len(found[0].markets) == 3
    assert event_sets({**event, "negRiskAugmented": False}) == []  # placeholder


def test_ladder_adds_the_fee_and_reads_no_off_the_yes_bids() -> None:
    fee = leg(1, feeSchedule={"rate": 0.05}, feesEnabled=True)
    b = book("y1", bids=[(0.30, 5), (0.25, 7)], asks=[(0.40, 10), (0.45, 3)])
    yes = ladder(KIND_YES, fee, b)
    assert [lv.price for lv in yes] == [
        pytest.approx(0.40 + 0.05 * 0.24),
        pytest.approx(0.45 + 0.05 * 0.2475),
    ]
    assert [lv.size for lv in yes] == [10, 3]
    no = ladder(KIND_NO, leg(1), b)
    assert [lv.price for lv in no] == [pytest.approx(0.70), pytest.approx(0.75)]
    assert [lv.size for lv in no] == [5, 7]


def test_steps_walk_every_leg_until_one_runs_out() -> None:
    a = [Level(0.3, 10), Level(0.4, 10)]
    b = [Level(0.5, 4), Level(0.6, 30)]
    walked = steps([a, b])
    assert [s.price for s in walked] == [
        pytest.approx(0.8),
        pytest.approx(0.9),
        pytest.approx(1.0),
    ]
    assert [s.size for s in walked] == [4, 6, 10]
    assert steps([a, []]) == [] and steps([]) == []


def test_cost_of_sums_the_walk_or_says_it_is_too_thin() -> None:
    walked = [Level(0.8, 4), Level(0.9, 6)]
    assert cost_of(walked, 5) == pytest.approx(4 * 0.8 + 0.9)
    assert cost_of(walked, 10) == pytest.approx(4 * 0.8 + 6 * 0.9)
    assert cost_of(walked, 11) is None


def test_quote_a_yes_set_with_depth() -> None:
    legs = (leg(1), leg(2))
    s = spec(KIND_YES, legs)
    books = {
        "y1": book("y1", asks=[(0.30, 20), (0.45, 200)], min_order_size=5),
        "y2": book("y2", asks=[(0.50, 50), (0.60, 200)], min_order_size=5),
    }
    q = quote(s, books, min_profit=0.005)
    assert q is not None and q.open
    # sets 1-20 cost 0.80, 21-50 cost 0.95, then 1.05: 50 sets worth buying
    assert q.best_cost == pytest.approx(0.80)
    assert q.max_size == pytest.approx(50)
    assert q.max_profit == pytest.approx(20 * 0.20 + 30 * 0.05)
    assert q.costs == (
        pytest.approx(8.0),
        pytest.approx(20 * 0.8 + 30 * 0.95),
        pytest.approx(20 * 0.8 + 30 * 0.95 + 50 * 1.05),
    )
    assert q.depth == pytest.approx(220) and q.min_order == 5
    row = q.row(s.payout)
    assert row["best_profit"] == pytest.approx(0.2) and row["cost_10"] == 8.0
    assert set(row) >= {f"cost_{n}" for n in DEPTHS}


def test_quote_a_no_set_and_the_thresholds() -> None:
    legs = (leg(1), leg(2), leg(3))
    s = spec(KIND_NO, legs)
    # No asks 0.65, 0.65, 0.65 = 1.95 for a payout of 2
    books = {t: book(t, bids=[(0.35, 8)], min_order_size=0) for t in s.tokens}
    q = quote(s, books, min_profit=0.005)
    assert q is not None and q.open and q.min_order == 5  # the market's minimum
    assert q.max_profit == pytest.approx(8 * 0.05) and q.costs == (None, None, None)
    dear = quote(s, books, min_profit=0.06)
    assert dear is not None and not dear.open  # not worth 6 c a set
    thin = {t: book(t, bids=[(0.35, 2)], min_order_size=5) for t in s.tokens}
    small = quote(s, thin, min_profit=0.005)
    assert small is not None and not small.open  # under the minimum order


def test_quote_without_a_book_or_a_level() -> None:
    s = spec(KIND_YES, (leg(1), leg(2)))
    assert quote(s, {"y1": book("y1", asks=[(0.3, 9)])}, min_profit=0.0) is None
    empty = quote(
        s, {"y1": book("y1", asks=[(0.3, 9)]), "y2": book("y2")}, min_profit=0.0
    )
    assert empty is not None and empty.best_cost is None and not empty.open
    assert empty.best_profit(1.0) is None and empty.row(1.0)["best_cost"] is None


def test_leg_levels_records_each_legs_top_levels() -> None:
    legs = (leg(1), leg(2))
    books = {"y1": book("y1", bids=[(0.3, 5), (0.2, 6)], asks=[(0.4, 1), (0.5, 2)])}
    assert leg_levels(spec(KIND_YES, legs), books, levels=1) == [[[0.4, 1]], []]
    assert leg_levels(spec(KIND_NO, legs), books) == [[[0.7, 5], [0.8, 6]], []]
