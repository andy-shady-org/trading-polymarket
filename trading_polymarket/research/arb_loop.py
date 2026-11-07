"""Record every full-set gap on Polymarket, how big and how long (FEAT-102).

``trading-polymarket arb --loop`` runs this, record-only, in tmux for a week
(``docs/dev/runs/arb-1.md``). Nothing is ever ordered. Each tick
(``recheck`` seconds, 5 by default) does, in this order:

1. **Catalogue** (every ``catalogue`` seconds, 900): one pass over every open
   Gamma event (``/events/keyset``, about 200 pages, 3 minutes), in the
   background so ticks go on; its neg-risk events' full sets
   (:func:`trading_polymarket.research.arb.event_sets`) replace the last
   ones when it ends. A gap whose set is gone is closed (``gone``).
2. **Recheck**: every open gap's books, read again (CLOB ``POST /books``).
3. **Watch** (every ``watch`` seconds, 30): sets whose last read was within
   ``watch_margin`` (3 c a set) of a gap.
4. **Sweep** (every ``sweep`` seconds, 300): every set, a slice of
   :data:`SWEEP_TOKENS` Yes books per tick, so a sweep of about 114,000
   books takes about a minute without holding up the rechecks.

A set read **open** (:class:`~trading_polymarket.research.arb.SetQuote`)
opens a gap, or extends it; a read that is not open, or a missing book,
closes it. Lifetimes are what the reads saw: ``lifetime`` runs from the first
open read to the last, so it is a lower bound, and ``closed_at`` is the first
read that found it gone.

Files, one folder per UTC day (``<dir>/<YYYY-MM-DD>/``), by the time written::

    catalogue.jsonl       {"rx", "seconds", "events", "neg_risk_events",
                           "sets", "augmented_sets", "legs", "no_full_set"}
    sweeps.jsonl          {"rx", "seconds", "sets", "tokens", "books",
                           "missing", "watched", "open"}
    observations.jsonl.gz [rx, key, best_cost, best_profit, max_size,
                           max_profit, cost_10, cost_50, cost_100,
                           min_order, legs]  (every read of an open gap;
                           legs: each leg's top 5 levels, [price, size])
    gaps.jsonl            the set (``SetSpec.row``) and "first_seen",
                          "last_open", "closed_at", "lifetime", "reads",
                          "first_max_profit", "first_max_size",
                          "peak_max_profit", "peak_max_size",
                          "peak_best_profit", "qualify", "run_seconds",
                          "run_reads", "censored", "reason"

Each catalogue pass and each finished sweep prints a status line.

``run_seconds`` is the longest span of consecutive reads each at least
``qualify`` dollars of profit (``max_profit``; $5, FEAT-102's rule), from the
first read of the run to its last; ``arb-report`` counts those of 10 s or
more. A gap still open when the recorder stops is written with
``"censored": true``.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_polymarket.book import OrderBook
from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.http import HttpError
from trading_polymarket.markets import markets_from_event
from trading_polymarket.research.arb import (
    DEFAULT_MIN_PROFIT,
    SetQuote,
    SetSpec,
    event_sets,
    leg_levels,
    quote,
)

DEFAULT_ARB_DIR = "data/arb"
RECHECK_SECONDS = 5.0
WATCH_SECONDS = 30.0
SWEEP_SECONDS = 300.0
CATALOGUE_SECONDS = 900.0
WATCH_MARGIN = 0.03
QUALIFY_PROFIT = 5.0
# Yes books read per tick in a sweep: 20 requests of 500.
SWEEP_TOKENS = 10_000
# Open Gamma events: 199 pages of 100 on 2026-11-07.
MAX_EVENT_PAGES = 500
# A failed catalogue pass is tried again after this long.
RETRY_SECONDS = 60.0

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[Any]]
Log = Callable[[str], None]


def day_of(rx: float) -> str:
    return datetime.fromtimestamp(rx, UTC).strftime("%Y-%m-%d")


class ArbWriter:
    """Append rows to the day's files; see the module docstring."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.counts: Counter[str] = Counter()

    def _path(self, rx: float, name: str) -> Path:
        folder = self.directory / day_of(rx)
        folder.mkdir(parents=True, exist_ok=True)
        return folder / name

    def rows(self, rx: float, name: str, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            return
        with self._path(rx, f"{name}.jsonl").open("a", encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(row, sort_keys=True) + "\n")
        self.counts[name] += len(rows)

    def observations(self, rx: float, rows: Sequence[Sequence[Any]]) -> None:
        if not rows:
            return
        path = self._path(rx, "observations.jsonl.gz")
        with gzip.open(path, "at", encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(list(row)) + "\n")
        self.counts["observations"] += len(rows)


@dataclass
class Gap:
    """One gap from its first open read to its last."""

    spec: SetSpec
    first: float
    first_quote: SetQuote
    qualify: float
    last: float = 0.0
    reads: int = 0
    peak_profit: float = 0.0
    peak_size: float = 0.0
    peak_best: float = 0.0
    run_start: float | None = None
    run_last: float = 0.0
    run_count: int = 0
    best_run: float = 0.0
    best_run_reads: int = 0

    def add(self, rx: float, q: SetQuote) -> None:
        self.last, self.reads = rx, self.reads + 1
        self.peak_profit = max(self.peak_profit, q.max_profit)
        self.peak_size = max(self.peak_size, q.max_size)
        self.peak_best = max(self.peak_best, q.best_profit(self.spec.payout) or 0.0)
        if q.max_profit < self.qualify:
            self.run_start = None
            return
        if self.run_start is None:
            self.run_start, self.run_count = rx, 0
        self.run_last, self.run_count = rx, self.run_count + 1
        if self.run_last - self.run_start >= self.best_run:
            self.best_run = self.run_last - self.run_start
            self.best_run_reads = self.run_count

    def row(self, closed_at: float | None, reason: str) -> dict[str, Any]:
        return {
            **self.spec.row(),
            "first_seen": self.first,
            "last_open": self.last,
            "closed_at": closed_at,
            "lifetime": round(self.last - self.first, 3),
            "reads": self.reads,
            "first_max_profit": round(self.first_quote.max_profit, 5),
            "first_max_size": round(self.first_quote.max_size, 4),
            "peak_max_profit": round(self.peak_profit, 5),
            "peak_max_size": round(self.peak_size, 4),
            "peak_best_profit": round(self.peak_best, 6),
            "qualify": self.qualify,
            "run_seconds": round(self.best_run, 3),
            "run_reads": self.best_run_reads,
            "censored": closed_at is None,
            "reason": reason,
        }


@dataclass
class Settings:
    min_profit: float = DEFAULT_MIN_PROFIT
    watch_margin: float = WATCH_MARGIN
    qualify: float = QUALIFY_PROFIT
    recheck: float = RECHECK_SECONDS
    watch: float = WATCH_SECONDS
    sweep: float = SWEEP_SECONDS
    catalogue: float = CATALOGUE_SECONDS
    sweep_tokens: int = SWEEP_TOKENS
    max_pages: int = MAX_EVENT_PAGES


async def read_catalogue(gamma: GammaClient, *, max_pages: int) -> Catalogue:
    """Every open neg-risk event's full sets (one pass over Gamma's events)."""
    found = Catalogue()
    async for page in gamma.event_pages(max_pages=max_pages, closed=False):
        for event in page:
            found.add(event, gamma.default_fee_rate)
    return found


@dataclass
class Catalogue:
    sets: dict[str, SetSpec] = field(default_factory=dict)
    events: int = 0
    neg_risk: int = 0
    no_full_set: int = 0

    def add(self, event: Mapping[str, Any], fee_rate: float) -> None:
        self.events += 1
        if not event.get("negRisk"):
            return
        self.neg_risk += 1
        found = event_sets(event, markets_from_event(event, default_fee_rate=fee_rate))
        self.no_full_set += not found
        self.sets.update((s.key, s) for s in found)

    def row(self, rx: float, seconds: float) -> dict[str, Any]:
        sets = list(self.sets.values())
        return {
            "rx": rx,
            "seconds": round(seconds, 1),
            "events": self.events,
            "neg_risk_events": self.neg_risk,
            "sets": len(sets),
            "augmented_sets": sum(s.augmented for s in sets),
            "legs": sum(len(s.markets) for s in sets) // 2,
            "no_full_set": self.no_full_set,
        }


@dataclass
class ArbRecorder:
    """The state between ticks; see the module docstring."""

    gamma: GammaClient
    clob: ClobClient
    writer: ArbWriter
    settings: Settings = field(default_factory=Settings)
    clock: Clock = time.time
    sets: dict[str, SetSpec] = field(default_factory=dict)
    gaps: dict[str, Gap] = field(default_factory=dict)
    watched: set[str] = field(default_factory=set)
    sweep_left: list[str] = field(default_factory=list)
    sweep_stats: Counter[str] = field(default_factory=Counter)
    due: dict[str, float] = field(default_factory=dict)
    loading: asyncio.Task[Catalogue] | None = None
    loading_since: float = 0.0
    errors: int = 0
    failure: str = ""
    notes: list[str] = field(default_factory=list)

    # -- reading and judging ----------------------------------------------
    async def read(self, keys: Iterable[str]) -> dict[str, OrderBook]:
        tokens = [t for k in keys if k in self.sets for t in self.sets[k].tokens]
        return await self.clob.books(tokens)

    def judge(self, keys: Iterable[str], books: Mapping[str, OrderBook]) -> int:
        """Price ``keys`` on ``books``: open, extend or close gaps; keep the
        watch list. Returns the sets read open."""
        rx = self.clock()
        rows: list[list[Any]] = []
        opened = 0
        for key in keys:
            spec = self.sets.get(key)
            if spec is None:
                continue
            q = quote(spec, books, min_profit=self.settings.min_profit)
            self._watch(key, spec, q)
            if q is not None and q.open:
                opened += 1
                self._extend(spec, q, rx)
                rows.append(_observation(rx, spec, q, books))
            elif key in self.gaps:
                self._close(key, rx, "no_book" if q is None else "closed")
        self.writer.observations(rx, rows)
        return opened

    def _watch(self, key: str, spec: SetSpec, q: SetQuote | None) -> None:
        best = None if q is None else q.best_profit(spec.payout)
        if best is not None and best >= -self.settings.watch_margin:
            self.watched.add(key)
        else:
            self.watched.discard(key)

    def _extend(self, spec: SetSpec, q: SetQuote, rx: float) -> None:
        gap = self.gaps.get(spec.key)
        if gap is None:
            gap = self.gaps[spec.key] = Gap(spec, rx, q, self.settings.qualify)
        gap.add(rx, q)

    def _close(self, key: str, rx: float | None, reason: str) -> None:
        gap = self.gaps.pop(key)
        self.writer.rows(rx or self.clock(), "gaps", [gap.row(rx, reason)])

    # -- the catalogue ----------------------------------------------------
    def _install(self, found: Catalogue) -> None:
        rx = self.clock()
        row = found.row(rx, rx - self.loading_since)
        self.writer.rows(rx, "catalogue", [row])
        self.notes.append(
            f"catalogue: {row['neg_risk_events']} neg-risk events, {row['sets']} "
            f"sets ({row['augmented_sets']} augmented) in {row['seconds']:.0f} s"
        )
        for key in [k for k in self.gaps if k not in found.sets]:
            self._close(key, rx, "gone")
        self.sets = found.sets
        self.watched &= set(found.sets)
        self.sweep_left = [k for k in self.sweep_left if k in found.sets]

    async def catalogue_step(self, now: float) -> None:
        """Start a catalogue pass when one is due; install it when done."""
        if self.loading is not None and self.loading.done():
            task, self.loading = self.loading, None
            error = task.exception()
            if error is None:
                self._install(task.result())
            else:
                self.errors += 1
                self.failure = f"catalogue failed: {error}"
                self.due["catalogue"] = now + RETRY_SECONDS
        if self.loading is None and now >= self.due.get("catalogue", 0.0):
            self.due["catalogue"] = now + self.settings.catalogue
            self.loading_since = now
            self.loading = asyncio.create_task(
                read_catalogue(self.gamma, max_pages=self.settings.max_pages)
            )
            await asyncio.sleep(0)

    # -- the tick ---------------------------------------------------------
    async def recheck_step(self) -> None:
        keys = list(self.gaps)
        if keys:
            self.judge(keys, await self.read(keys))

    async def watch_step(self, now: float) -> None:
        if now < self.due.get("watch", 0.0):
            return
        self.due["watch"] = now + self.settings.watch
        keys = [k for k in self.watched if k not in self.gaps]
        if keys:
            self.judge(keys, await self.read(keys))

    async def sweep_step(self, now: float) -> None:
        if not self.sweep_left:
            if now < self.due.get("sweep", 0.0) or not self.sets:
                return
            self.due["sweep"] = now + self.settings.sweep
            self.sweep_left = list(self.sets)
            self.sweep_stats = Counter(started=int(now))
        keys = self._slice()
        books = await self.read(keys)
        tokens = len({t for k in keys for t in self.sets[k].tokens})
        self.sweep_stats.update(
            sets=len(keys), tokens=tokens, books=len(books), missing=tokens - len(books)
        )
        self.sweep_stats["open"] += self.judge(keys, books)
        if not self.sweep_left:
            self._sweep_done()

    def _slice(self) -> list[str]:
        keys: list[str] = []
        tokens = 0
        while self.sweep_left and tokens < self.settings.sweep_tokens:
            key = self.sweep_left.pop()
            keys.append(key)
            tokens += len(self.sets[key].tokens)
        return keys

    def _sweep_done(self) -> None:
        rx = self.clock()
        stats = self.sweep_stats
        row: dict[str, Any] = {
            k: stats[k] for k in ("sets", "tokens", "books", "missing", "open")
        }
        row.update(
            rx=rx, seconds=round(rx - stats["started"], 1), watched=len(self.watched)
        )
        self.writer.rows(rx, "sweeps", [row])
        self.notes.append(
            f"sweep: {row['sets']} sets, {row['books']} books in "
            f"{row['seconds']:.0f} s; {row['open']} open, {len(self.gaps)} gaps, "
            f"{row['watched']} watched, {self.writer.counts['gaps']} gaps written"
        )

    async def tick(self) -> None:
        now = self.clock()
        await self.catalogue_step(now)
        await self.recheck_step()
        await self.watch_step(now)
        await self.sweep_step(now)

    async def stop(self) -> None:
        """Write the gaps still open (censored) and drop a pending catalogue."""
        for key in list(self.gaps):
            self._close(key, None, "stopped")
        if self.loading is not None:
            self.loading.cancel()
            await asyncio.gather(self.loading, return_exceptions=True)
            self.loading = None


def _observation(
    rx: float, spec: SetSpec, q: SetQuote, books: Mapping[str, OrderBook]
) -> list[Any]:
    row = q.row(spec.payout)
    return [
        rx,
        spec.key,
        row["best_cost"],
        row["best_profit"],
        row["max_size"],
        row["max_profit"],
        row["cost_10"],
        row["cost_50"],
        row["cost_100"],
        row["min_order"],
        leg_levels(spec, books),
    ]


async def scan_once(
    gamma: GammaClient,
    clob: ClobClient,
    *,
    min_profit: float = DEFAULT_MIN_PROFIT,
    max_pages: int = MAX_EVENT_PAGES,
) -> tuple[Catalogue, list[tuple[SetSpec, SetQuote]]]:
    """One catalogue pass and one read of every set (``arb`` without
    ``--loop``): the sets priced, closest to a gap first."""
    found = await read_catalogue(gamma, max_pages=max_pages)
    specs = list(found.sets.values())
    books = await clob.books(t for spec in specs for t in spec.tokens)
    priced = [
        (spec, q)
        for spec in specs
        if (q := quote(spec, books, min_profit=min_profit)) is not None
    ]
    priced.sort(key=lambda p: _closeness(*p), reverse=True)
    return found, priced


def _closeness(spec: SetSpec, q: SetQuote) -> float:
    best = q.best_profit(spec.payout)
    return float("-inf") if best is None else best


async def record(
    gamma: GammaClient,
    clob: ClobClient,
    *,
    directory: str | Path = DEFAULT_ARB_DIR,
    hours: float | None = None,
    settings: Settings | None = None,
    clock: Clock = time.time,
    sleep: Sleep = asyncio.sleep,
    log: Log = print,
) -> Counter[str]:
    """Record until ``hours`` pass (or the task is cancelled); the rows written.

    A tick that fails (an HTTP error after retries) is counted and logged and
    the next runs at its time; a failed catalogue pass is retried when next
    due. The gaps still open are written, censored, however it stops."""
    recorder = ArbRecorder(
        gamma, clob, ArbWriter(directory), settings or Settings(), clock=clock
    )
    end = None if hours is None else clock() + hours * 3600.0
    try:
        while end is None or clock() < end:
            started = clock()
            await _tick(recorder, log)
            await sleep(max(0.0, recorder.settings.recheck - (clock() - started)))
    finally:
        await recorder.stop()
    return recorder.writer.counts


async def _tick(recorder: ArbRecorder, log: Log) -> None:
    try:
        await recorder.tick()
    except HttpError as exc:
        recorder.errors += 1
        log(f"tick failed ({recorder.errors} so far): {exc}")
    if recorder.failure:
        log(f"{recorder.failure} ({recorder.errors} errors so far); retried soon")
        recorder.failure = ""
    for note in recorder.notes:
        log(note)
    recorder.notes.clear()


__all__ = [
    "CATALOGUE_SECONDS",
    "DEFAULT_ARB_DIR",
    "MAX_EVENT_PAGES",
    "QUALIFY_PROFIT",
    "RECHECK_SECONDS",
    "RETRY_SECONDS",
    "SWEEP_SECONDS",
    "SWEEP_TOKENS",
    "WATCH_MARGIN",
    "WATCH_SECONDS",
    "ArbRecorder",
    "ArbWriter",
    "Catalogue",
    "Gap",
    "Settings",
    "read_catalogue",
    "record",
    "scan_once",
]
