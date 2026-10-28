from __future__ import annotations

import pytest

from trading_polymarket.calibration import CalibrationTable
from trading_polymarket.config import FavouriteLane
from trading_polymarket.research.backtest import (
    BacktestResult,
    backtest_favourite,
    brier_scores,
    calibrate,
    observations,
    split_rows,
)
from trading_polymarket.research.history import HistoryRow
from trading_polymarket.tests.support.factories import NOW, history_row

H = 3600.0


def row(i: int, winner: int = 0, price: float = 0.85, end: float = NOW) -> HistoryRow:
    return HistoryRow.from_dict(
        history_row(
            market_id=str(i),
            winner=winner,
            end_time=end,
            prices=[(end - 80 * H, price), (end - 0.5 * H, 0.99)],
            fee_rate=0.02,
        )
    )


def test_brier_scores_and_summary() -> None:
    assert brier_scores([]) == {}
    scores = brier_scores([(1.0, 0.5, 0.75, True), (0.0, 0.5, 0.25, False)])
    assert scores == {"buckets": 2, "model": 0.0, "market": 0.25, "blend": 0.0625}
    result = BacktestResult([], 0, 1, 0.0, scores=scores)
    assert result.summary()["scores"]["market"] == 0.25
    assert "scores" not in BacktestResult([], 0, 1, 0.0).summary()


def test_observations_take_both_tokens_at_each_horizon() -> None:
    obs = list(observations([row(1)], horizons=(24.0, 100.0)))
    assert [(o.price, o.won) for o in obs] == [
        (0.85, True),
        (pytest.approx(0.15), False),
    ]
    edge = HistoryRow.from_dict(history_row(prices=[(NOW - 30 * H, 1.0)]))
    assert list(observations([edge], horizons=(24.0,))) == []


def test_split_and_calibrate() -> None:
    rows = [row(1, end=NOW - 10 * H), row(2, end=NOW)]
    train, test = split_rows(rows, NOW - H)
    assert [r.market_id for r in train] == ["1"] and [r.market_id for r in test] == [
        "2"
    ]
    table = calibrate(rows, horizons=(24.0,))
    assert table.meta["markets"] == 2 and table.samples(0.85, 24) == 2
    assert calibrate([]).meta["first_close"] is None


def favourite_table(won: int, n: int = 300) -> CalibrationTable:
    rows = [row(i, winner=0 if i < won else 1) for i in range(n)]
    return calibrate(rows, horizons=(24.0,), prior_strength=10)


def test_backtest_takes_the_first_qualifying_entry_and_holds() -> None:
    lane = FavouriteLane(enabled=True, min_samples=100, min_edge=0.01, max_hours=48)
    table = favourite_table(won=290)
    result = backtest_favourite(
        [row(1000), row(1001, winner=1)],
        table,
        lane,
        bankroll=1000,
        horizons=(24.0, 12.0),
    )
    assert isinstance(result, BacktestResult) and result.trades == 2
    assert len(result.records) == 4
    buy = result.records[0]["payload"]
    assert (
        buy["strategy"] == "favourite" and buy["entry_metrics"]["hours_to_close"] == 24
    )
    assert result.records[0]["timestamp"] == NOW - 24 * H
    assert result.summary()["trades"] == 2
    assert result.net == pytest.approx(
        sum(r["payload"]["net_pnl"] for r in result.records), abs=1e-3
    )


def test_backtest_skips_without_edge_samples_band_or_size() -> None:
    lane = FavouriteLane(enabled=True, min_samples=100, min_edge=0.01)
    assert backtest_favourite([row(1)], favourite_table(won=250), lane).trades == 0
    assert backtest_favourite([row(1)], CalibrationTable(), lane).trades == 0
    assert (
        backtest_favourite([row(1, price=0.5)], favourite_table(290), lane).trades == 0
    )
    tiny = FavouriteLane(enabled=True, min_samples=100, min_notional=24.9)
    assert (
        backtest_favourite([row(1)], favourite_table(290), tiny, bankroll=10).trades
        == 0
    )
    empty = HistoryRow.from_dict(history_row(prices=[(NOW + H, 0.9)]))
    assert backtest_favourite([empty], favourite_table(290), lane).trades == 0
