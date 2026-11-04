"""Unit tests for ``research/updown_stale.py``: FEAT-147's rule."""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from trading_polymarket.research.updown import (
    SpotDay,
    UpDownMarket,
    day_start,
    spot_path,
)
from trading_polymarket.research.updown_backtest import PRIMARY as LONGSHOT
from trading_polymarket.research.updown_backtest import Summary
from trading_polymarket.research.updown_stale import (
    GRID,
    PRIMARY,
    STRESS,
    SpotSeries,
    StaleRule,
    _Prints,
    distance,
    entry,
    fill,
    replay,
    signal,
    verdict,
)
from trading_polymarket.research.updown_stale import spot_path as path_of

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


def spot_at(path: dict[int, float]) -> Callable[[float], float | None]:
    """Spot known at second τ (the candle that ended there) from {τ: price}."""

    def at(moment: float) -> float | None:
        return path.get(int(moment - START) + 1)

    return at


FLAT = {0: 100_000.0}
# Up is 1 bp behind at 250 s: within -1.5 bp, so Up qualifies there.
NEAR = {0: 100_000.0, 249: 99_970.0, 250: 99_990.0}


def test_rules_are_named_and_the_grid_starts_with_the_primary() -> None:
    assert PRIMARY.name == "cap 5c from 240s spot -1.5bp 2s late"
    assert STRESS.latency == 3.0 and GRID[0] == PRIMARY and len(GRID) == 9
    assert StaleRule(threshold=0).name.endswith("spot +0bp 2s late")


def test_distance_is_toward_the_outcome() -> None:
    assert distance(100.01, 100.0, UP) == pytest.approx(1.0)
    assert distance(100.01, 100.0, DOWN) == pytest.approx(-1.0)


def test_the_signal_needs_spot_near_the_line_and_a_cheap_last_print() -> None:
    cheap = market((100, UP, BUY, 0.03, 500), (100, DOWN, BUY, 0.97, 500))
    prints = _Prints.of(cheap.trades, 0.0)
    assert signal(cheap, PRIMARY, path_of(cheap, spot_at(NEAR)), prints) == (250, UP)
    # The Down side, when spot is past the line its way.
    down = {0: 100_000.0, 250: 99_990.0}
    pricey = market((100, DOWN, SELL, 0.04, 5), (100, UP, BUY, 0.96, 5))
    pricey_prints = _Prints.of(pricey.trades, 0.0)
    assert signal(pricey, PRIMARY, path_of(pricey, spot_at(down)), pricey_prints) == (
        250,
        DOWN,
    )
    # No start price, no prints yet, a pricey side, spot too far: no signal.
    assert signal(cheap, PRIMARY, [], prints) is None
    assert signal(cheap, PRIMARY, [None] * 300, prints) is None
    late = _Prints.of(((280, UP, BUY, 0.03, 500, "w"),), 0.0)
    far = {0: 100_000.0, 250: 99_900.0}
    assert signal(cheap, PRIMARY, path_of(cheap, spot_at(far)), late) is None
    dear = _Prints.of(((100, UP, BUY, 0.20, 500, "w"),), 0.0)
    assert signal(cheap, PRIMARY, path_of(cheap, spot_at(NEAR)), dear) is None


def test_the_fill_waits_for_the_latency_and_a_real_print() -> None:
    m = market(
        (251, UP, BUY, 0.03, 500),  # before τ + 2 s
        (252, DOWN, BUY, 0.03, 500),  # the other side
        (252, UP, SELL, 0.03, 500),  # a sale
        (253, UP, BUY, 0.07, 500),  # above cap + 1 c
        (253, UP, BUY, 0.04, 10),  # under the stake
        (254, UP, BUY, 0.06, 100),  # the fill
    )
    assert fill(m, PRIMARY, (250, UP), offset=0.0, stake=5.0) == (
        254.0,
        m.trades[-1],
    )
    # With the data API's time 3 s after the fill, the same print is 251.
    assert fill(m, PRIMARY, (250, UP), offset=3.0, stake=5.0) is None
    assert fill(m, PRIMARY, (240, UP), offset=0.0, stake=5.0) is None  # past τ+L+5
    assert fill(m, PRIMARY, (295, UP), offset=0.0, stake=5.0) is None  # window ends


def test_an_entry_is_made_held_and_priced() -> None:
    m = market((100, UP, BUY, 0.03, 500), (253, UP, BUY, 0.04, 500), winner=UP)
    e = entry(m, PRIMARY, spot_at(NEAR))
    assert e is not None
    assert (e.outcome, e.signal_t, e.fill_t, e.price, e.won) == (
        UP,
        250,
        253,
        0.04,
        True,
    )
    assert e.fee == pytest.approx(5 / 0.04 * 0.07 * 0.04 * 0.96, abs=1e-5)
    assert entry(m, PRIMARY, spot_at(FLAT | {250: 99_000.0})) is None  # no signal
    unfilled = market((100, UP, BUY, 0.03, 500))
    assert entry(unfilled, PRIMARY, spot_at(NEAR)) is None


def test_replay_runs_every_rule_in_one_pass() -> None:
    m = market((100, UP, BUY, 0.03, 500), (253, UP, BUY, 0.04, 500))
    count, found = replay([m, market()], spot_at(NEAR), [PRIMARY, STRESS], stake=2.0)
    assert count == 2 and len(found[PRIMARY]) == 1 and len(found[STRESS]) == 1
    assert found[PRIMARY][0].stake == 2.0


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


def test_spot_is_read_from_the_backfill_by_day(tmp_path: Path) -> None:
    closes: list[float | None] = [None] * 86400
    closes[3599] = 100.0
    path = spot_path(tmp_path, "BTCUSDT", DAY)
    path.parent.mkdir(parents=True)
    day = SpotDay("BTCUSDT", day_start(DAY), tuple(closes))
    path.write_bytes(gzip.compress(json.dumps(day.to_dict()).encode()))
    series = SpotSeries(tmp_path, "BTCUSDT")
    assert series(START - 1) == 100.0 and series(START + 50) == 100.0
    assert series(day_start(DAY) - 10) is None  # the day before: not collected
