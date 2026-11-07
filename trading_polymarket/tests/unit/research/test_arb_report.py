from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from trading_polymarket.research.arb_report import (
    GO,
    INCONCLUSIVE,
    MIN_SWEEPS,
    NO_GO,
    annualized,
    days_to_resolution,
    gap_day,
    load,
    qualifies,
    summarize,
    verdict,
)
from trading_polymarket.tests.support.factories import NOW

DAY = 86400.0


def gap(day: int = 0, **extra: Any) -> dict[str, Any]:
    return {
        "first_seen": NOW + day * DAY,
        "augmented": False,
        "qualify": 5.0,
        "run_seconds": 10.0,
        "lifetime": 30.0,
        "peak_max_profit": 6.0,
        "peak_max_size": 50.0,
        "kind": "yes_set",
        "tags": ["sports"],
        **extra,
    }


def test_a_gap_qualifies_with_five_dollars_for_ten_seconds_outside_augmented():
    assert qualifies(gap())
    assert not qualifies(gap(run_seconds=9.9))
    assert not qualifies(gap(augmented=True))
    assert not qualifies(gap(qualify=4.0))  # recorded at a lower bar
    assert not qualifies({"first_seen": NOW})


def test_load_reads_the_days_in_range_and_skips_junk(tmp_path: Path) -> None:
    for name, n_gaps, n_sweeps in (("2026-11-08", 2, 3), ("2026-11-09", 1, 0)):
        folder = tmp_path / name
        folder.mkdir()
        lines = [json.dumps(gap()) for _ in range(n_gaps)] + ["not json", "[1]"]
        (folder / "gaps.jsonl").write_text("\n".join(lines) + "\n")
        if n_sweeps:
            (folder / "sweeps.jsonl").write_text("{}\n" * n_sweeps)
    (tmp_path / "notes").mkdir()
    (tmp_path / "README").write_text("x")
    gaps, sweeps = load(tmp_path)
    assert len(gaps) == 3 and sweeps == {"2026-11-08": 3, "2026-11-09": 0}
    gaps, sweeps = load(tmp_path, start=date(2026, 11, 9), end=date(2026, 11, 10))
    assert len(gaps) == 1 and list(sweeps) == ["2026-11-09"]
    assert load(tmp_path / "missing") == ([], Counter())


def days(n: int) -> list[str]:
    return [f"2026-11-{8 + i:02d}" for i in range(n)]


def test_verdict_needs_seven_covered_days_a_mean_of_ten_and_five_in_seven():
    assert verdict(dict.fromkeys(days(6), 50), days(6)) == INCONCLUSIVE
    assert verdict(dict.fromkeys(days(7), 10), days(7)) == GO
    # a mean of 10 carried by two big days is not enough
    lumpy = {d: (30 if i < 2 else 2) for i, d in enumerate(days(7))}
    assert sum(lumpy.values()) / 7 >= 10 and verdict(lumpy, days(7)) == NO_GO
    # five of seven days at the bar, with the mean there too
    five = {d: (14 if i < 5 else 0) for i, d in enumerate(days(7))}
    assert verdict(five, days(7)) == GO
    four = {d: (20 if i < 4 else 0) for i, d in enumerate(days(7))}
    assert verdict(four, days(7)) == NO_GO
    assert verdict({}, days(8)) == NO_GO
    # eight days: ceil(5/7 * 8) = 6 must reach the bar
    six = {d: (12 if i < 6 else 4) for i, d in enumerate(days(8))}
    assert verdict(six, days(8)) == GO
    seven_of_eight = {d: (20 if i < 5 else 0) for i, d in enumerate(days(8))}
    assert verdict(seven_of_eight, days(8)) == NO_GO


def test_summarize_counts_by_day_kind_and_tag_with_augmented_apart() -> None:
    gaps = [
        gap(0),
        gap(0, run_seconds=3.0, kind="no_set", tags=[]),
        gap(1, augmented=True),
        gap(1, censored=True, peak_max_profit=12.0),
    ]
    first, second = gap_day(gaps[0]), gap_day(gaps[2])
    summary = summarize(gaps, Counter({first: MIN_SWEEPS, second: 10}))
    assert summary["gaps"] == 3 and summary["augmented_gaps"] == 1
    assert summary["qualifying"] == 2 and summary["censored"] == 1
    assert summary["qualifying_peak_profit"] == pytest.approx(18.0)
    assert summary["covered_days"] == 1 and summary["verdict"] == INCONCLUSIVE
    assert summary["by_kind"] == {
        "no_set": {"gaps": 1, "qualifying": 0},
        "yes_set": {"gaps": 2, "qualifying": 2},
    }
    assert summary["by_tag"]["-"] == {"gaps": 1, "qualifying": 0}
    day0, day1 = summary["days"]
    assert day0 == {
        "day": first,
        "sweeps": MIN_SWEEPS,
        "covered": True,
        "gaps": 2,
        "augmented_gaps": 0,
        "qualifying": 1,
    }
    assert day1["augmented_gaps"] == 1 and not day1["covered"]
    assert summary["lifetime"]["p50"] == 30.0
    assert summary["peak_max_profit"]["max"] == 12.0


def test_days_to_resolution_and_the_return_a_year() -> None:
    # 100 sets of a $1 set at 0.95: $5 on $95, resolving in 365 days
    g = gap(resolves=NOW + 365 * DAY, first_max_size=100.0, first_max_profit=5.0)
    g["payout"] = 1.0
    assert days_to_resolution(g) == pytest.approx(365.0)
    assert annualized(g) == pytest.approx(5 / 95)
    assert annualized({**g, "resolves": NOW + 730 * DAY}) == pytest.approx(5 / 190)
    assert days_to_resolution(gap()) is None and annualized(gap()) is None
    assert annualized({**g, "resolves": NOW - DAY}) is None  # already due
    assert annualized({**g, "first_max_size": 0.0}) is None


def test_summarize_reports_the_qualifying_gaps_horizon() -> None:
    g = gap(resolves=NOW + 30 * DAY, first_max_size=100.0, first_max_profit=5.0)
    g["payout"] = 1.0
    summary = summarize([g, gap()], Counter())
    assert summary["qualifying_days_to_resolution"]["p50"] == pytest.approx(30.0)
    assert summary["qualifying_annualized"]["max"] == pytest.approx(5 / 95 * 365 / 30)


def test_summarize_an_empty_recording() -> None:
    summary = summarize([], Counter())
    assert summary["days"] == [] and summary["lifetime"] is None
    assert summary["verdict"] == INCONCLUSIVE
