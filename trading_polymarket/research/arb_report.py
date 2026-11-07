"""Read an ``arb --loop`` recording and judge FEAT-102's rule (``arb-report``).

FEAT-102's decision rule, written before the week
(``docs/dev/PROPOSED-FEATURES.md``, made exact in ``docs/dev/runs/arb-1.md``):
an executor is worth building only if, after fees, there are at least 10
gaps a day of at least $5 each at a fillable size, lasting at least 10 s.

* **A qualifying gap:** a set of an event that is not augmented, with a run
  of consecutive reads, each with at least $5 of profit at the size that
  still earns ``min_profit`` a set (``max_profit``), spanning at least
  :data:`MIN_RUN_SECONDS` (``run_seconds`` in ``gaps.jsonl``, from the
  recorder's ``qualify`` of $5). It is counted on the UTC day it was first
  seen.
* **A covered day:** a UTC day with at least :data:`MIN_SWEEPS` finished
  sweeps (of 288 at one every 5 minutes), so the recorder saw the market.
* **Verdict:** INCONCLUSIVE with fewer than :data:`MIN_DAYS` covered days;
  GO when the covered days average at least :data:`MIN_PER_DAY` qualifying
  gaps **and** at least 5 in 7 of them (:data:`MIN_DAY_SHARE`) reach it;
  NO-GO otherwise.

Everything else is reported, not deciding: gaps by kind and by the event's
first tag, augmented events apart, lifetimes, sizes and profits, and for the
qualifying gaps the days until their set resolves and the return a year on
the money a set ties up (profit over cost at the first read's ``max_size``,
per year to resolution): a gap that pays 2.5 c a set two years out is less
than cash earns (two such sets were open on 2026-11-07).
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from trading_polymarket.research.arb_loop import day_of

MIN_PROFIT_DOLLARS = 5.0
MIN_RUN_SECONDS = 10.0
MIN_PER_DAY = 10
MIN_DAYS = 7
MIN_DAY_SHARE = 5 / 7
MIN_SWEEPS = 240

GO, NO_GO, INCONCLUSIVE = "GO", "NO-GO", "INCONCLUSIVE"


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def _in_range(name: str, start: date | None, end: date | None) -> bool:
    try:
        day = date.fromisoformat(name)
    except ValueError:
        return False
    return (start is None or day >= start) and (end is None or day < end)


def load(
    directory: str | Path, *, start: date | None = None, end: date | None = None
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """The gaps written in ``[start, end)`` and the finished sweeps per day."""
    gaps: list[dict[str, Any]] = []
    sweeps: Counter[str] = Counter()
    root = Path(directory)
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        if folder.is_dir() and _in_range(folder.name, start, end):
            gaps.extend(_rows(folder / "gaps.jsonl"))
            sweeps[folder.name] += sum(1 for _ in _rows(folder / "sweeps.jsonl"))
    return gaps, sweeps


def gap_day(gap: Mapping[str, Any]) -> str:
    return day_of(float(gap["first_seen"]))


def qualifies(gap: Mapping[str, Any]) -> bool:
    return (
        not gap.get("augmented")
        and float(gap.get("qualify") or 0.0) >= MIN_PROFIT_DOLLARS
        and float(gap.get("run_seconds") or 0.0) >= MIN_RUN_SECONDS
    )


def _quantiles(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)

    def pick(share: float) -> float:
        return ordered[min(len(ordered) - 1, int(share * len(ordered)))]

    return {
        "p10": pick(0.10),
        "p50": statistics.median(ordered),
        "p90": pick(0.90),
        "max": ordered[-1],
    }


def annualized(gap: Mapping[str, Any]) -> float | None:
    """The first read's profit over the money its sets tie up, a year."""
    days = days_to_resolution(gap)
    size = float(gap.get("first_max_size") or 0.0)
    profit = float(gap.get("first_max_profit") or 0.0)
    capital = size * float(gap.get("payout") or 0.0) - profit
    if days is None or days <= 0 or capital <= 0:
        return None
    return profit / capital * 365.0 / days


def days_to_resolution(gap: Mapping[str, Any]) -> float | None:
    resolves = gap.get("resolves")
    if resolves is None:
        return None
    return (float(resolves) - float(gap["first_seen"])) / 86400.0


def verdict(per_day: Mapping[str, int], covered: Sequence[str]) -> str:
    if len(covered) < MIN_DAYS:
        return INCONCLUSIVE
    counts = [per_day.get(day, 0) for day in covered]
    mean = sum(counts) / len(counts)
    at_bar = sum(c >= MIN_PER_DAY for c in counts)
    enough = at_bar >= math.ceil(MIN_DAY_SHARE * len(counts) - 1e-9)
    return GO if mean >= MIN_PER_DAY and enough else NO_GO


def _by(gaps: Sequence[Mapping[str, Any]], key: str) -> dict[str, dict[str, int]]:
    out: dict[str, Counter[str]] = defaultdict(Counter)
    for gap in gaps:
        tags = gap.get("tags") or [""]
        name = str(gap.get(key) if key != "tag" else tags[0]) or "-"
        out[name]["gaps"] += 1
        out[name]["qualifying"] += qualifies(gap)
    return {k: dict(v) for k, v in sorted(out.items())}


def summarize(
    gaps: Sequence[Mapping[str, Any]], sweeps: Counter[str]
) -> dict[str, Any]:
    plain = [g for g in gaps if not g.get("augmented")]
    good = [g for g in plain if qualifies(g)]
    per_day = Counter(gap_day(g) for g in good)
    covered = sorted(d for d, n in sweeps.items() if n >= MIN_SWEEPS)
    days = sorted(set(sweeps) | {gap_day(g) for g in gaps})
    return {
        "days": [
            {
                "day": d,
                "sweeps": sweeps.get(d, 0),
                "covered": d in covered,
                "gaps": sum(gap_day(g) == d for g in plain),
                "augmented_gaps": sum(gap_day(g) == d for g in gaps)
                - sum(gap_day(g) == d for g in plain),
                "qualifying": per_day.get(d, 0),
            }
            for d in days
        ],
        "gaps": len(plain),
        "augmented_gaps": len(gaps) - len(plain),
        "qualifying": len(good),
        "censored": sum(bool(g.get("censored")) for g in gaps),
        "by_kind": _by(plain, "kind"),
        "by_tag": _by(plain, "tag"),
        "lifetime": _quantiles([float(g["lifetime"]) for g in plain]),
        "peak_max_profit": _quantiles([float(g["peak_max_profit"]) for g in plain]),
        "peak_max_size": _quantiles([float(g["peak_max_size"]) for g in plain]),
        "qualifying_peak_profit": round(
            sum(float(g["peak_max_profit"]) for g in good), 2
        ),
        "qualifying_days_to_resolution": _quantiles(
            [d for d in (days_to_resolution(g) for g in good) if d is not None]
        ),
        "qualifying_annualized": _quantiles(
            [a for a in (annualized(g) for g in good) if a is not None]
        ),
        "covered_days": len(covered),
        "verdict": verdict(per_day, covered),
    }


__all__ = [
    "GO",
    "INCONCLUSIVE",
    "MIN_DAYS",
    "MIN_DAY_SHARE",
    "MIN_PER_DAY",
    "MIN_PROFIT_DOLLARS",
    "MIN_RUN_SECONDS",
    "MIN_SWEEPS",
    "NO_GO",
    "annualized",
    "days_to_resolution",
    "gap_day",
    "load",
    "qualifies",
    "summarize",
    "verdict",
]
