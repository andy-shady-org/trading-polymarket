from __future__ import annotations

import pytest

from trading_polymarket.config import WeatherLane
from trading_polymarket.fees import FeeSchedule
from trading_polymarket.strategies.common import (
    kelly_fraction,
    net_edge,
    plan_buy,
    token_ask,
    token_mid,
)
from trading_polymarket.tests.support.factories import NO, YES, book, market

LANE = WeatherLane(min_edge=0.05, kelly_fraction=0.5, min_notional=1, max_notional=50)


def test_net_edge_and_kelly() -> None:
    assert net_edge(0.7, 0.5, FeeSchedule(rate=0.04)) == pytest.approx(0.19)
    assert kelly_fraction(0.7, 0.5) == pytest.approx(0.4)
    assert kelly_fraction(0.4, 0.5) == 0.0
    assert kelly_fraction(1.0, 1.0) == 0.0


def test_plan_buy_stops_at_the_first_level_without_edge() -> None:
    b = book(asks=[(0.50, 10), (0.55, 10), (0.70, 100)])
    plan = plan_buy(b, 0.65, FeeSchedule(), LANE, bankroll=1000)
    assert plan is not None
    assert plan.limit == 0.55 and plan.available == pytest.approx(10.5)
    assert plan.notional == pytest.approx(10.5)  # capped by the book
    assert plan.edge == pytest.approx(0.65 - plan.average_price)
    assert set(plan.metrics()) >= {"limit", "edge", "kelly", "avg_price"}


def test_plan_buy_sizes_with_fractional_kelly_and_caps() -> None:
    b = book(asks=[(0.50, 1000)])
    plan = plan_buy(b, 0.6, FeeSchedule(), LANE, bankroll=100)
    assert plan is not None
    assert plan.notional == pytest.approx(0.5 * 0.2 * 100)
    capped = plan_buy(b, 0.9, FeeSchedule(), LANE, bankroll=10_000)
    assert capped is not None and capped.notional == pytest.approx(50)


def test_plan_buy_refuses_without_edge_or_size() -> None:
    b = book(asks=[(0.50, 1000)])
    assert plan_buy(b, 0.52, FeeSchedule(), LANE, bankroll=1000) is None
    assert plan_buy(b, 0.9, FeeSchedule(), LANE, bankroll=1000, max_price=0.4) is None
    assert plan_buy(b, 0.56, FeeSchedule(), LANE, bankroll=10) is None  # < $1


def test_token_ask_and_mid() -> None:
    m = market()
    assert token_ask(m, YES) == 0.61 and token_ask(m, NO) == pytest.approx(0.41)
    assert token_mid(m, YES) == pytest.approx(0.60)
    assert token_mid(m, NO) == pytest.approx(0.40)
    blank = market(bestBid=None, bestAsk=None)
    assert token_ask(blank, NO) is None and token_mid(blank, YES) is None
