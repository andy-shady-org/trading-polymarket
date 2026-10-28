"""Invariants of fees, book walking, bucket probabilities and calibration."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trading_polymarket.book import OrderBook
from trading_polymarket.calibration import CalibrationTable, Observation
from trading_polymarket.execution import floor_to, trim_walk
from trading_polymarket.fees import FeeSchedule
from trading_polymarket.strategies.weather import TempDistribution

prices = st.floats(min_value=0.01, max_value=0.99, allow_nan=False)
sizes = st.floats(min_value=0.01, max_value=10_000, allow_nan=False)
levels = st.lists(st.tuples(prices, sizes), min_size=0, max_size=8)


@given(rate=st.floats(min_value=0, max_value=0.2), price=prices, shares=sizes)
def test_fee_is_bounded_and_peaks_at_even_odds(
    rate: float, price: float, shares: float
) -> None:
    fee = FeeSchedule(rate=rate)
    assert 0 <= fee.taker_fee(shares, price) <= shares * rate * 0.25 + 1e-5
    assert fee.per_share(price) <= fee.per_share(0.5) + 1e-12


@given(asks=levels, notional=st.floats(min_value=0, max_value=50_000), limit=prices)
def test_a_buy_never_overspends_or_pays_above_its_limit(
    asks: list[tuple[float, float]], notional: float, limit: float
) -> None:
    book = OrderBook.from_levels("t", [], asks)
    walk = book.walk_buy(notional, limit=limit)
    assert walk.notional <= notional + 1e-6
    assert all(part.price <= limit + 1e-9 for part in walk.parts)
    assert walk.size <= sum(s for _, s in asks) + 1e-6
    trimmed = trim_walk(walk, floor_to(walk.size, 2))
    assert trimmed.size <= walk.size + 1e-9 and trimmed.notional <= walk.notional + 1e-9


@given(bids=levels, size=sizes, limit=prices)
def test_a_sell_never_sells_more_than_asked_or_below_its_limit(
    bids: list[tuple[float, float]], size: float, limit: float
) -> None:
    walk = OrderBook.from_levels("t", bids, []).walk_sell(size, limit=limit)
    assert walk.size <= size + 1e-6
    assert all(part.price >= limit - 1e-9 for part in walk.parts)


@given(
    mu=st.floats(min_value=-30, max_value=45),
    sigma=st.floats(min_value=0.1, max_value=6),
    floor=st.one_of(st.none(), st.floats(min_value=-30, max_value=45)),
    edges=st.lists(st.integers(-20, 110), min_size=1, max_size=12, unique=True),
    unit=st.sampled_from(["C", "F"]),
)
def test_bucket_probabilities_partition_one(
    mu: float, sigma: float, floor: float | None, edges: list[int], unit: str
) -> None:
    cuts = sorted(edges)
    dist = TempDistribution(mu=mu, sigma=sigma, floor=floor)
    ranges: list[tuple[int | None, int | None]] = [(None, cuts[0] - 1)]
    ranges += [(low, high - 1) for low, high in zip(cuts, cuts[1:], strict=False)]
    ranges += [(cuts[-1], None)]
    probabilities = [dist.range_probability(lo, hi, unit) for lo, hi in ranges]
    assert all(0 <= p <= 1 for p in probabilities)
    assert sum(probabilities) == pytest.approx(1.0, abs=1e-9)


@given(
    observations=st.lists(
        st.tuples(prices, st.floats(min_value=0, max_value=200), st.booleans()),
        max_size=60,
    ),
    price=prices,
    hours=st.floats(min_value=0, max_value=200),
)
def test_calibrated_win_rate_is_a_probability(
    observations: list[tuple[float, float, bool]], price: float, hours: float
) -> None:
    table = CalibrationTable.build(Observation(p, h, w) for p, h, w in observations)
    assert 0.0 <= table.win_rate(price, hours) <= 1.0
