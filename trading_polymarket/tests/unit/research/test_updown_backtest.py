"""Unit tests for ``research/updown_backtest.py``: the late-longshot replay."""

from __future__ import annotations

from datetime import date

import pytest

from trading_polymarket.research.updown import UpDownMarket, day_start
from trading_polymarket.research.updown_backtest import (
    GRID,
    PRIMARY,
    Entry,
    Rule,
    audit_records,
    binomial_tail,
    entry,
    replay,
    roi,
    summarise,
    without_top,
)

DAY = date(2026, 10, 5)
START = day_start(DAY)
UP, DOWN = 0, 1
BUY, SELL = 1, -1


def market(
    *trades: tuple[float, int, int, float, float], winner: int = UP
) -> UpDownMarket:
    return UpDownMarket(
        slug="btc-updown-5m-x",
        condition_id="0xc",
        start=START,
        end=START + 300,
        winner=winner,
        price_to_beat=None,
        final_price=None,
        fee_rate=0.07,
        volume=0.0,
        trades=tuple((*t, "0xw") for t in trades),
    )


def made(
    price: float = 0.04, won: bool = True, *, day: date = DAY, stake: float = 5.0
) -> Entry:
    start = day_start(day)
    return Entry("m", start, start + 300, UP, 250, 251, price, won, stake, 0.0)


def test_rules_are_named_and_the_grid_holds_the_primary() -> None:
    assert PRIMARY.name == "cap 5c from 240s"
    assert Rule(0.05, 0, until=180).name == "cap 5c from 0s until 180s"
    assert PRIMARY in GRID and len(GRID) == 10


def test_the_fill_is_the_next_big_enough_buy_in_a_later_second() -> None:
    m = market(
        (100, UP, BUY, 0.03, 500),  # before 240 s: no signal
        (241, UP, SELL, 0.02, 500),  # a sale is not a signal
        (242, UP, BUY, 0.04, 500),  # the signal
        (242.5, UP, BUY, 0.04, 500),  # the same second: not the fill
        (243, DOWN, BUY, 0.04, 500),  # the other outcome
        (244, UP, BUY, 0.07, 500),  # above cap + 1c
        (245, UP, BUY, 0.05, 50),  # $2.50: under the stake
        (246, UP, SELL, 0.05, 500),  # a sale
        (247, UP, BUY, 0.06, 100),  # the fill: $6 at 6c
    )
    e = entry(m, PRIMARY)
    assert e is not None
    assert (e.outcome, e.signal_t, e.fill_t, e.price, e.won) == (
        UP,
        242,
        247,
        0.06,
        True,
    )
    assert e.day == DAY and e.shares == pytest.approx(5 / 0.06)
    assert e.fee == pytest.approx(5 / 0.06 * 0.07 * 0.06 * 0.94, abs=1e-5)
    assert e.profit == pytest.approx(5 / 0.06 - 5 - e.fee)


def test_a_loser_costs_the_stake_and_the_fee() -> None:
    m = market((250, DOWN, BUY, 0.03, 500), (251, DOWN, BUY, 0.03, 500))
    e = entry(m, PRIMARY)
    assert e is not None and not e.won and e.profit == pytest.approx(-5 - e.fee)


@pytest.mark.parametrize(
    "trades",
    [
        (),  # nothing traded
        ((250, UP, BUY, 0.30, 500),),  # nothing cheap
        ((299, UP, BUY, 0.03, 500), (300, UP, BUY, 0.03, 500)),  # fill after the end
        ((300, UP, BUY, 0.03, 500), (301, UP, BUY, 0.03, 500)),  # all after the end
        ((250, UP, BUY, 0.03, 500), (251, UP, BUY, 0.03, 1)),  # nothing big enough
    ],
)
def test_no_signal_or_no_fill_is_no_entry(
    trades: tuple[tuple[float, int, int, float, float], ...],
) -> None:
    assert entry(market(*trades), PRIMARY) is None


def test_until_ends_an_early_rule() -> None:
    early = Rule(cap=0.05, start=0, until=180)
    m = market((170, UP, BUY, 0.03, 500), (185, UP, BUY, 0.03, 500))
    assert entry(m, early) is None
    m = market((10, UP, BUY, 0.03, 500), (11, UP, BUY, 0.03, 500))
    e = entry(m, early)
    assert e is not None and e.fill_t == 11


def test_replay_runs_every_rule_in_one_pass() -> None:
    m = market((250, UP, BUY, 0.03, 500), (251, UP, BUY, 0.03, 500))
    count, found = replay([m, market()], [PRIMARY, Rule(0.02, 240)], stake=2.0)
    assert count == 2 and len(found[PRIMARY]) == 1 and found[Rule(0.02, 240)] == []
    assert found[PRIMARY][0].stake == 2.0


def test_binomial_tail() -> None:
    assert binomial_tail(0, 10, 0.5) == 1.0
    assert binomial_tail(11, 10, 0.5) == 0.0
    assert binomial_tail(3, 10, 0.0) == 0.0
    assert binomial_tail(3, 10, 1.0) == 1.0
    assert binomial_tail(10, 10, 0.5) == pytest.approx(0.5**10)
    assert binomial_tail(9, 10, 0.5) == pytest.approx(11 / 1024)


def test_roi_and_dropping_the_best() -> None:
    assert roi([]) is None
    entries = [made(0.05, True), made(0.05, False), made(0.05, False)]
    assert roi(entries) == pytest.approx((100 - 15) / 15)
    assert without_top(entries) == [made(0.05, False), made(0.05, False)]
    assert without_top([]) == []


def test_a_summary_passes_only_on_every_check() -> None:
    split = date(2026, 10, 6)
    second = date(2026, 10, 7)
    winners = [made(0.04, True, day=d) for d in (DAY, DAY, second, second)]
    losers = [made(0.04, False, day=d) for d in (DAY, second)] * 10
    good = summarise(PRIMARY, 100, winners + losers, split=split)
    assert good.passed and good.entries == 24 and good.wins == 4
    assert good.average_price == pytest.approx(0.04)
    assert good.p_value is not None and good.p_value < 0.05
    row = good.to_dict()
    assert row["rule"] == PRIMARY.name and row["passed"] is True
    one_half = summarise(PRIMARY, 100, winners[:2] + losers, split=split)
    second_half = one_half.roi_halves[1]
    assert not one_half.passed and second_half is not None and second_half < 0
    empty = summarise(PRIMARY, 100, [], split=split)
    assert not empty.passed and empty.win_rate is None and empty.p_value is None
    # A positive return that is not a significant win rate does not pass.
    lucky = summarise(
        PRIMARY, 100, [made(0.5, True, day=d) for d in (DAY, second)], split=split
    )
    assert lucky.roi_without_top is not None and lucky.p_value == pytest.approx(0.25)
    assert not lucky.passed


def test_audit_records_are_round_trips_at_settlement() -> None:
    records = audit_records([made(0.04, True), made(0.04, False)], PRIMARY)
    assert len(records) == 4
    assert all(r["payload"]["strategy"] == "updown-longshot" for r in records)
    sells = [r["payload"] for r in records if r["payload"]["action"] == "sell"]
    assert [s["price"] for s in sells] == [1.0, 0.0]
    assert records[1]["timestamp"] == START + 300
