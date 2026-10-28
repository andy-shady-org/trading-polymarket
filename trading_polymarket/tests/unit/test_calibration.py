from __future__ import annotations

import pytest

from trading_polymarket.calibration import (
    CalibrationTable,
    Observation,
    load_or_identity,
)


def table(n_wins: int = 95, n: int = 100, price: float = 0.9) -> CalibrationTable:
    obs = [Observation(price, 10, i < n_wins) for i in range(n)]
    return CalibrationTable.build(obs, prior_strength=50)


def test_empty_cell_maps_price_to_itself() -> None:
    empty = CalibrationTable()
    assert empty.win_rate(0.42, 5) == 0.42
    assert empty.samples(0.42, 5) == 0
    assert empty.edge(0.42, 5) == 0.0


def test_win_rate_is_shrunk_towards_the_cell_price() -> None:
    t = table()
    # (95 + 50 x 0.9) / 150 = 0.9333
    assert t.win_rate(0.9, 10) == pytest.approx(140 / 150)
    assert t.samples(0.9, 10) == 100
    assert t.edge(0.9, 10) == pytest.approx(140 / 150 - 0.9)
    # Same cell, a slightly lower price: shifted by the gap to the cell mean.
    assert t.win_rate(0.91, 10) == pytest.approx(140 / 150 + 0.01)
    # A price in another (empty) cell maps to itself.
    assert t.win_rate(0.89, 10) == 0.89


def test_win_rate_is_clamped() -> None:
    t = CalibrationTable.build([Observation(0.99, 1, True)] * 10, prior_strength=0)
    assert t.win_rate(0.999, 1) == 1.0
    low = CalibrationTable.build([Observation(0.01, 1, False)] * 10, prior_strength=0)
    assert low.win_rate(0.0, 1) == 0.0


def test_bins_clamp_out_of_range_values() -> None:
    t = CalibrationTable()
    assert t.key(-1, -5) == "0:0"
    assert t.key(2, 10**9) == f"{len(t.price_edges) - 2}:{len(t.hour_edges) - 2}"


def test_rows_report_each_cell() -> None:
    rows = table().rows()
    assert len(rows) == 1
    row = rows[0]
    assert (row["price_lo"], row["price_hi"]) == (0.9, 0.93)
    assert row["n"] == 100 and row["win_rate"] == 0.95
    assert row["mean_price"] == pytest.approx(0.9)
    t = CalibrationTable(counts={"0:0": [0.0, 0.0, 0.0]})
    assert t.rows()[0]["mean_price"] == 0.0


def test_save_load_round_trip_and_hash(tmp_path) -> None:  # noqa: ANN001
    t = table()
    t.meta = {"markets": 3}
    path = t.save(tmp_path / "sub" / "cal.json")
    loaded = CalibrationTable.load(path)
    assert loaded.to_dict() == t.to_dict()
    assert loaded.sha256() == t.sha256()
    assert load_or_identity(path).samples(0.9, 10) == 100


def test_identity_without_a_file(tmp_path) -> None:  # noqa: ANN001
    assert load_or_identity("").meta == {"identity": True}
    assert load_or_identity(str(tmp_path / "missing.json")).meta["identity"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"price_edges": (0.0,)},
        {"price_edges": (0.5, 0.1)},
        {"hour_edges": (1.0, 1.0)},
        {"prior_strength": -1},
    ],
)
def test_invalid_tables(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        CalibrationTable(**kwargs)


def test_wrong_version_is_refused() -> None:
    with pytest.raises(ValueError):
        CalibrationTable.from_dict({"version": 99})
