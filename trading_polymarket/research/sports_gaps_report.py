"""Gaps between Polymarket and Kalshi after a match is listed (FEAT-168).

Reads ``sports-gaps record``'s files (``research/sports_gaps.py``) and finds
every **gap**: a snapshot in which buying a side on Polymarket at its ask,
with Polymarket's taker fee, costs at least ``gap`` less than Kalshi's mid
for the same side, while Kalshi's book is no wider than
``max_kalshi_spread`` (a reference worth trusting) and the ask holds at
least ``min_notional`` USDC. This is the 2026-10-30 study's fed-style rule
on recorded asks instead of hourly mids. Consecutive gap snapshots of one
side are one **event**, entered at the first snapshot's ask and held to
settlement; an event's net per dollar is ``(1 if the side won else 0 -
cost) / cost``.

Each event records how long after the match was listed on both venues it
came (the study's gaps came in the first hours), which venue listed it
first, how long it lasted (snapshots, about 2 minutes apart) and how much
was offered. :func:`decision` applies the pre-registered rules of the run
record ``docs/dev/runs/sports-1.md``. Nothing is traded.
"""

from __future__ import annotations

import gzip
import json
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.fees import FeeSchedule

HOUR = 3600.0
# Hours after both venues had listed the match, for the summary's buckets.
AGE_BUCKETS: tuple[tuple[str, float], ...] = (
    ("0-1 h", 1.0),
    ("1-3 h", 3.0),
    ("3-12 h", 12.0),
    ("12 h+", float("inf")),
)
# Pre-registered (docs/dev/runs/sports-1.md).
MIN_EVENTS = 30
MIN_MATCHES = 15
MIN_SETTLED = 30
MIN_MEDIAN_NOTIONAL = 20.0
MIN_DAYS = 7
MAX_DAYS = 28


@dataclass(frozen=True)
class GapRule:
    gap: float = 0.02
    max_kalshi_spread: float = 0.05
    min_notional: float = 5.0


PRIMARY = GapRule()


@dataclass(frozen=True)
class PairInfo:
    key: str
    sport: str
    slug: str
    fee: FeeSchedule
    pm_created: float
    kalshi_created: float
    start: float

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> PairInfo:
        return cls(
            key=str(row["pair"]),
            sport=str(row.get("sport") or ""),
            slug=str(row.get("pm_slug") or ""),
            fee=FeeSchedule.from_gamma(row.get("pm_fee"), default_rate=0.05),
            pm_created=float(row["pm_created"]),
            kalshi_created=float(row["kalshi_created"]),
            start=float(row["start"]),
        )

    @property
    def listed(self) -> float:
        """When both venues had listed the match."""
        return max(self.pm_created, self.kalshi_created)


Side = tuple[float | None, float | None, float | None, float | None]


def side_view(row: Sequence[Any], side: int) -> Side:
    """(Polymarket ask, its size, Kalshi bid, Kalshi ask) for one side of a
    quote row. The second side's Polymarket ask mirrors the first side's bid
    (1 - bid, same size)."""
    if side == 0:
        ask, size = row[4], row[5]
        kalshi = row[6:10]
    else:
        ask = None if row[2] is None else 1.0 - float(row[2])
        size = row[3]
        kalshi = row[10:14]
    return ask, size, kalshi[0], kalshi[2]


@dataclass(frozen=True)
class Gap:
    ask: float
    cost: float
    kalshi_mid: float
    edge: float
    notional: float


def gap_at(
    row: Sequence[Any], side: int, fee: FeeSchedule, rule: GapRule
) -> Gap | None:
    ask, size, k_bid, k_ask = side_view(row, side)
    if ask is None or size is None or k_bid is None or k_ask is None:
        return None
    if k_ask - k_bid > rule.max_kalshi_spread or ask <= 0.0:
        return None
    cost = ask + fee.per_share(ask)
    mid = (k_bid + k_ask) / 2.0
    notional = float(size) * ask
    if mid - cost < rule.gap or notional < rule.min_notional:
        return None
    return Gap(ask, cost, mid, mid - cost, notional)


@dataclass
class Event:
    pair: str
    side: int
    sport: str
    slug: str
    first_rx: float
    last_rx: float
    snapshots: int
    gap: Gap
    hours_after_listing: float
    hours_before_start: float
    pm_listed_first: bool
    won: bool | None = None

    @property
    def net_per_dollar(self) -> float | None:
        if self.won is None:
            return None
        return ((1.0 if self.won else 0.0) - self.gap.cost) / self.gap.cost

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["net_per_dollar"] = self.net_per_dollar
        return out


def _start_event(info: PairInfo, side: int, rx: float, gap: Gap) -> Event:
    return Event(
        pair=info.key,
        side=side,
        sport=info.sport,
        slug=info.slug,
        first_rx=rx,
        last_rx=rx,
        snapshots=1,
        gap=gap,
        hours_after_listing=(rx - info.listed) / HOUR,
        hours_before_start=(info.start - rx) / HOUR,
        pm_listed_first=info.pm_created <= info.kalshi_created,
    )


def side_events(
    info: PairInfo, rows: Sequence[Sequence[Any]], side: int, rule: GapRule
) -> list[Event]:
    """One side's events: runs of consecutive gap snapshots."""
    found: list[Event] = []
    current: Event | None = None
    for row in rows:
        gap = gap_at(row, side, info.fee, rule)
        if gap is None:
            current = None
        elif current is None:
            current = _start_event(info, side, float(row[0]), gap)
            found.append(current)
        else:
            current.last_rx, current.snapshots = float(row[0]), current.snapshots + 1
    return found


def find_events(
    pairs: Mapping[str, PairInfo],
    quotes: Iterable[Sequence[Any]],
    rule: GapRule = PRIMARY,
) -> list[Event]:
    by_pair: dict[str, list[Sequence[Any]]] = defaultdict(list)
    for row in quotes:
        if row[1] in pairs:
            by_pair[row[1]].append(row)
    found: list[Event] = []
    for key, rows in sorted(by_pair.items()):
        rows.sort(key=lambda r: r[0])
        for side in (0, 1):
            found.extend(side_events(pairs[key], rows, side, rule))
    found.sort(key=lambda e: e.first_rx)
    return found


@dataclass
class Recording:
    days: list[str]
    pairs: dict[str, PairInfo]
    quotes: list[list[Any]]
    listings: int = 0


def load_recording(directory: str | Path) -> Recording:
    root = Path(directory)
    days = sorted(p.name for p in root.glob("????-??-??") if p.is_dir())
    pairs: dict[str, PairInfo] = {}
    quotes: list[list[Any]] = []
    listings = 0
    for day in days:
        folder = root / day
        for row in _jsonl(folder / "pairs.jsonl"):
            info = PairInfo.from_row(row)
            pairs.setdefault(info.key, info)
        listings += sum(1 for _ in _jsonl(folder / "listings.jsonl"))
        path = folder / "quotes.jsonl.gz"
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                quotes.extend(json.loads(line) for line in handle if line.strip())
    return Recording(days, pairs, quotes, listings)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def winner_of(raw: Mapping[str, Any]) -> int | None:
    """The winning side of a closed two-outcome market (prices 1 and 0)."""
    try:
        prices = [float(p) for p in json.loads(raw.get("outcomePrices") or "[]")]
    except (TypeError, ValueError):
        return None
    if sorted(prices) != [0.0, 1.0]:
        return None
    return prices.index(1.0)


async def fetch_winners(gamma: GammaClient, slugs: Sequence[str]) -> dict[str, int]:
    raw = await gamma.raw_markets_by_slugs(sorted(set(slugs)), closed=True)
    out: dict[str, int] = {}
    for market in raw:
        winner = winner_of(market)
        if winner is not None:
            out[str(market.get("slug"))] = winner
    return out


def settle(events: Iterable[Event], winners: Mapping[str, int]) -> None:
    for event in events:
        if event.slug in winners:
            event.won = winners[event.slug] == event.side


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _bucket(hours: float) -> str:
    return next(name for name, top in AGE_BUCKETS if hours < top)


def summarize(events: Sequence[Event], midpoint: float) -> dict[str, Any]:
    nets = [(e, n) for e in events if (n := e.net_per_dollar) is not None]
    halves = (
        [n for e, n in nets if e.first_rx < midpoint],
        [n for e, n in nets if e.first_rx >= midpoint],
    )
    ages = [_bucket(e.hours_after_listing) for e in events]
    by_age = {name: ages.count(name) for name, _ in AGE_BUCKETS}
    return {
        "events": len(events),
        "matches": len({e.pair for e in events}),
        "by_sport": dict(sorted(_count(e.sport for e in events).items())),
        "by_hours_after_listing": by_age,
        "pm_listed_first": sum(e.pm_listed_first for e in events),
        "median_edge": _median([e.gap.edge for e in events]),
        "median_notional": _median([e.gap.notional for e in events]),
        "median_minutes": _median([(e.last_rx - e.first_rx) / 60.0 for e in events]),
        "settled": len(nets),
        "won": sum(1 for e, _ in nets if e.won),
        "net_per_dollar": _mean([n for _, n in nets]),
        "net_per_dollar_halves": [_mean(h) for h in halves],
    }


def _count(items: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for item in items:
        out[item] += 1
    return dict(out)


def decision(days: int, summary: Mapping[str, Any]) -> str:
    """The run record's verdict (docs/dev/runs/sports-1.md)."""
    if days < MIN_DAYS:
        return f"too early: {days} of at least {MIN_DAYS} days"
    enough = summary["events"] >= MIN_EVENTS and summary["matches"] >= MIN_MATCHES
    if not enough or summary["settled"] < MIN_SETTLED:
        return "EXTEND" if days < MAX_DAYS else "NO-GO: too few gaps"
    halves = summary["net_per_dollar_halves"]
    if any(h is None or h <= 0.0 for h in halves):
        return "NO-GO: not positive in both halves"
    if (summary["median_notional"] or 0.0) < MIN_MEDIAN_NOTIONAL:
        return "NO-GO: too little offered at the gap"
    return "GO"


__all__ = [
    "AGE_BUCKETS",
    "PRIMARY",
    "Event",
    "Gap",
    "GapRule",
    "PairInfo",
    "Recording",
    "decision",
    "fetch_winners",
    "find_events",
    "gap_at",
    "load_recording",
    "settle",
    "side_events",
    "side_view",
    "summarize",
    "winner_of",
]
