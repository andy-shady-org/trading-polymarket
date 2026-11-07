"""Unit tests for ``research/updown_fade.py``: FEAT-103's expiry fade."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date

import pytest

from trading_polymarket.research.updown import UpDownMarket, day_start
from trading_polymarket.research.updown_backtest import PRIMARY as LONGSHOT
from trading_polymarket.research.updown_backtest import Summary
from trading_polymarket.research.updown_fade import (
    GRID,
    MIRROR,
    PRIMARY,
    STRESS,
    FadeRule,
    entry,
    fill,
    replay,
    signal,
    verdict,
)
from trading_polymarket.research.updown_stale import _Prints, spot_path

DAY = date(2026, 11, 5)
START = day_start(DAY) + 3600
UP, DOWN = 0, 1
BUY, SELL = 1, -1


def market(
    *trades: tuple[float, int, int, float, float], winner: int = UP
) -> UpDownMarket:
    return UpDownMarket(
        "btc-updown-5m-x",
        "0xc",
        START,
        START + 300,
        winner,
        None,
        None,
        0.07,
        0.0,
        tuple((*t, "0xw") for t in trades),
    )


def spot(moves: dict[int, float] | None = None) -> Callable[[float], float | None]:
    """Spot at second τ: 100,000, or ``moves[τ]`` (``nan`` for no close)."""
    moves = moves or {}

    def at(moment: float) -> float | None:
        price = moves.get(int(moment - START) + 1, 100_000.0)
        return None if math.isnan(price) else price

    return at


def found(m: UpDownMarket, rule: FadeRule, moves: dict[int, float] | None = None):
    return signal(m, rule, spot_path(m, spot(moves)), _Prints.of(m.trades, 0.0))


def test_rules_are_named_and_the_grid_starts_with_the_primary() -> None:
    assert PRIMARY.name == "fade 15c from 50c, 300-60s left, spot <6bp/60s"
    assert MIRROR.name.startswith("favourite 15c") and STRESS.latency == 3.0
    assert STRESS.name.endswith(", 3s late") and GRID[:3] == (PRIMARY, MIRROR, STRESS)
    assert FadeRule(flat_bps=math.inf).name.endswith(", any spot")


def test_the_fade_buys_the_cheap_side_once_spot_has_been_flat() -> None:
    m = market((10, UP, BUY, 0.30, 100), (12, DOWN, BUY, 0.70, 100))
    # The spot test needs 60 s of spot: the first second it can pass.
    assert found(m, PRIMARY) == (60, UP, 0.30)
    assert found(m, MIRROR) == (60, DOWN, 0.70)
    # 10 bp in the minute before: not flat until that move is a minute old.
    assert found(m, PRIMARY, {60: 100_100.0, 61: 100_100.0})[0] == 62
    assert found(m, FadeRule(flat_bps=math.inf)) == (10, UP, 0.30)
    # A second with no close is not flat.
    assert found(m, PRIMARY, {60: math.nan})[0] == 61
    assert found(m, PRIMARY, {0: math.nan})[0] == 61


def test_the_signal_needs_a_side_far_enough_from_half_in_the_window() -> None:
    near = market((10, UP, BUY, 0.40, 100))
    assert found(near, PRIMARY) is None
    assert found(near, FadeRule(distance=0.10)) == (60, UP, 0.40)
    late = market((245, UP, BUY, 0.20, 100))  # under 60 s left: too late
    assert found(late, PRIMARY) is None
    both = market((10, UP, BUY, 0.30, 100), (11, DOWN, BUY, 0.20, 100))
    assert found(both, PRIMARY) == (60, DOWN, 0.20)  # the further one
    assert found(market(), PRIMARY) is None


def test_the_fill_is_a_real_buy_print_in_a_later_second() -> None:
    seen = (60, UP, 0.30)
    m = market(
        (60.5, UP, BUY, 0.30, 100),  # the signal's own second
        (61, UP, SELL, 0.30, 100),
        (61.5, DOWN, BUY, 0.70, 100),
        (62, UP, BUY, 0.32, 100),  # more than 1 c above
        (63, UP, BUY, 0.31, 10),  # too small for the stake
        (64, UP, BUY, 0.31, 100),
    )
    assert fill(m, PRIMARY, seen, offset=0.0, stake=5.0) == (64, m.trades[-1])
    assert fill(m, STRESS, seen, offset=0.0, stake=5.0) == (64, m.trades[-1])
    late = market((66, UP, BUY, 0.30, 100))  # past the 5 s span
    assert fill(late, PRIMARY, seen, offset=0.0, stake=5.0) is None
    shifted = market((62, UP, BUY, 0.30, 100))
    assert fill(shifted, PRIMARY, seen, offset=1.5, stake=5.0) is None
    assert fill(market(), PRIMARY, seen, offset=0.0, stake=5.0) is None


def test_an_entry_is_held_to_settlement_with_the_fee() -> None:
    m = market((10, UP, BUY, 0.30, 100), (61, UP, BUY, 0.30, 100), winner=UP)
    path, prints = spot_path(m, spot()), _Prints.of(m.trades, 0.0)
    made = entry(m, PRIMARY, path=path, prints=prints)
    assert made is not None and made.won and made.price == 0.30
    assert (made.signal_t, made.fill_t) == (60, 61)
    assert made.fee == pytest.approx(5.0 / 0.30 * 0.07 * 0.30 * 0.70, abs=1e-5)
    unfilled = market((10, UP, BUY, 0.30, 100))
    assert entry(unfilled, PRIMARY, path=path, prints=prints) is None
    assert entry(market(), PRIMARY, path=path, prints=_Prints.of((), 0.0)) is None


def test_replay_runs_every_rule_in_one_pass() -> None:
    m = market((10, UP, BUY, 0.30, 100), (61, UP, BUY, 0.30, 100))
    count, made = replay([m, market()], spot(), [PRIMARY, MIRROR], stake=2.0)
    assert count == 2 and len(made[PRIMARY]) == 1 and made[MIRROR] == []
    assert made[PRIMARY][0].stake == 2.0


def summary(entries: int, roi: float, passed: bool) -> Summary:
    good = 0.1 if passed else -0.1
    return Summary(
        LONGSHOT,
        1000,
        entries,
        10,
        0.0,
        0.0,
        roi,
        (good, good),
        good,
        0.02,
        0.05,
        0.001,
    )


def test_the_verdict() -> None:
    assert verdict(summary(199, 0.5, True), summary(199, 0.5, True)) == "INCONCLUSIVE"
    assert verdict(summary(200, 0.5, True), summary(200, 0.0, True)) == "PASS"
    assert verdict(summary(200, 0.5, True), summary(200, -0.01, True)) == "FAIL"
    assert verdict(summary(200, 0.5, False), summary(200, 0.5, True)) == "FAIL"
