"""Polymarket's collected data as strategy-library rows (``lane-rows``, FEAT-149).

``trading-polymarket lane-rows --from history --input data/history/markets.jsonl
--out data/lanes/markets.jsonl.gz`` writes the venue-neutral rows of
trading-core's strategy library (its ADR-011), the rows
``trading-core-lanes sweep --capture NAME=FILE`` reads, from data already
collected, so trading-core's outcome-market rules (``probability_band``,
``reference_gap``) can be swept over Polymarket's history:

* ``history`` (``data/history/markets.jsonl``) and ``weather-history``
  (``data/history/weather.jsonl``): each outcome token is an instrument (its
  token id). A ``listing`` at its first price point, ``resolves_at`` the
  market's end; a ``reading`` per price point (the first token's price, the
  other token's ``1 - p``); an ``outcome`` at the end, 1 for the winner;
* ``fed-history`` (``data/history/fed.jsonl``): the same per bucket, each
  reading's ``reference`` Kalshi's mid from the last hourly candle that had
  ended by then (no look-ahead; ``1 - mid`` for the No token), the outcome
  Polymarket's settlement at Kalshi's close;
* ``updown-history`` (``data/updown/<asset>-<window>/``): each market's Up and
  Down sides (``<condition id>:up`` / ``:down``), listed at the window's
  start, a ``reading`` and a ``trade`` per taker trade (the data API names
  the taker's wallet; the amount is price × shares, USDC), an ``outcome`` at
  the window's end. ``print_offset`` (seconds, FEAT-147's ``ticks-report``)
  is added to every print's time.

Polymarket's taker fee is ``rate × (p(1 − p))^exponent`` a share and its rate
differs by category, so a sweep takes one rate (``trading-core-lanes sweep
--price-fee-rate``): ``fee_rate`` keeps only the markets at that rate, and the
counts say which rates the input holds. Prices outside ``(0, 1]`` and points
at or after a market's end are skipped and counted.
"""

from __future__ import annotations

import gzip
import json
import math
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TextIO

from trading_core.lanes.market import (
    SIDE_BUY,
    SIDE_SELL,
    Listing,
    Outcome,
    Reading,
    Record,
    TradePrint,
    to_row,
)

from trading_polymarket.clients.kalshi import candle_at
from trading_polymarket.research.fed import FedBucket, FedMeeting, load_meetings
from trading_polymarket.research.history import HistoryRow, load_rows
from trading_polymarket.research.updown import UpDownMarket, load_markets
from trading_polymarket.research.weather_backtest import EventHistory, load_events

SOURCE_HISTORY = "history"
SOURCE_WEATHER = "weather-history"
SOURCE_FED = "fed-history"
SOURCE_UPDOWN = "updown-history"
SOURCES = (SOURCE_HISTORY, SOURCE_WEATHER, SOURCE_FED, SOURCE_UPDOWN)
KIND_MARKET = "market"
OUTPUT_SUFFIXES = (".jsonl", ".jsonl.gz")
UPDOWN_SIDES = ("up", "down")
# Two fee rates within this are one rate (they are read from floats).
_RATE_TOLERANCE = 1e-9

SKIP_PRICE = "price outside (0, 1]"
SKIP_AFTER_END = "point at or after the market's end"
SKIP_EMPTY = "market with no price point"
SKIP_FEE = "market at another fee rate"
SKIP_PRINT = "trade print outside its window"


@dataclass
class LaneRowStats:
    """What a conversion wrote and skipped, and the fee rates it saw."""

    markets: int = 0
    rows: Counter[str] = field(default_factory=Counter)
    skipped: Counter[str] = field(default_factory=Counter)
    fee_rates: Counter[float] = field(default_factory=Counter)


@dataclass(frozen=True)
class _Side:
    """One outcome token's prices, its settlement and the market's terms."""

    instrument: str
    points: Sequence[tuple[float, float]]
    end: float
    won: bool
    references: Sequence[float | None] | None = None


class Converter:
    """Turns markets into records, counting what it keeps and skips;
    ``fee_rate`` keeps only the markets at that taker fee rate."""

    def __init__(self, fee_rate: float | None) -> None:
        self.fee_rate = fee_rate
        self.stats = LaneRowStats()

    def wanted(self, rate: float) -> bool:
        """Count the market's fee rate; whether it is the one asked for."""
        self.stats.fee_rates[round(rate, 6)] += 1
        if self.fee_rate is None or abs(rate - self.fee_rate) <= _RATE_TOLERANCE:
            self.stats.markets += 1
            return True
        self.stats.skipped[SKIP_FEE] += 1
        return False

    def side(self, side: _Side) -> Iterator[Record]:
        """A listing at the first kept point, a reading per point, the outcome."""
        kept = list(self._kept(side))
        if not kept:
            self.stats.skipped[SKIP_EMPTY] += 1
            return
        yield Listing(
            side.instrument, kept[0][0], kind=KIND_MARKET, resolves_at=side.end
        )
        for at, price, reference in kept:
            yield Reading(side.instrument, at, price, reference=reference)
        yield Outcome(side.instrument, side.end, 1.0 if side.won else 0.0)

    def _kept(self, side: _Side) -> Iterator[tuple[float, float, float | None]]:
        references = side.references or [None] * len(side.points)
        for (at, price), reference in zip(side.points, references, strict=True):
            if at >= side.end:
                self.stats.skipped[SKIP_AFTER_END] += 1
            elif not 0.0 < price <= 1.0:
                self.stats.skipped[SKIP_PRICE] += 1
            else:
                yield at, price, reference


def _complement(points: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    """The other token's prices: ``1 - p`` (rounded as the collectors round)."""
    return [(at, round(1.0 - price, 6)) for at, price in points]


# The sources -----------------------------------------------------------------


def history_records(rows: Iterable[HistoryRow], conv: Converter) -> Iterator[Record]:
    """``history``: both tokens of every resolved binary market."""
    for row in rows:
        if not conv.wanted(row.fee_rate):
            continue
        prices = (list(row.history), _complement(row.history))
        for index, token in enumerate(row.token_ids[:2]):
            yield from conv.side(
                _Side(token, prices[index], row.end_time, row.winner == index)
            )


def weather_records(
    events: Iterable[EventHistory], conv: Converter
) -> Iterator[Record]:
    """``weather-history``: the Yes and No token of every bucket."""
    for event in events:
        for bucket in event.buckets:
            if not conv.wanted(bucket.fee_rate):
                continue
            yes, no = list(bucket.history), _complement(bucket.history)
            end = event.end_time
            yield from conv.side(_Side(bucket.yes_token, yes, end, bucket.won))
            yield from conv.side(_Side(bucket.no_token, no, end, not bucket.won))


def _kalshi_mids(bucket: FedBucket) -> list[float | None]:
    """Kalshi's mid from the last candle ended by each Polymarket point."""
    mids: list[float | None] = []
    for at, _ in bucket.pm:
        candle = candle_at(bucket.kalshi, at)
        mids.append(None if candle is None else candle.mid)
    return mids


def fed_records(meetings: Iterable[FedMeeting], conv: Converter) -> Iterator[Record]:
    """``fed-history``: each bucket's Yes and No token, Kalshi as reference."""
    for meeting in meetings:
        for bucket in meeting.buckets:
            if not conv.wanted(bucket.fee_rate):
                continue
            mids = _kalshi_mids(bucket)
            no_mids = [None if m is None else round(1.0 - m, 6) for m in mids]
            end = meeting.close_time
            yes = _Side(bucket.yes_token, list(bucket.pm), end, bucket.won, mids)
            no = _Side(
                bucket.no_token, _complement(bucket.pm), end, not bucket.won, no_mids
            )
            yield from conv.side(yes)
            yield from conv.side(no)


def updown_records(
    markets: Iterable[UpDownMarket], conv: Converter, print_offset: float = 0.0
) -> Iterator[Record]:
    """``updown-history``: each market's Up and Down sides, every taker trade
    a reading and a print, shifted by ``print_offset`` seconds."""
    for market in markets:
        if not conv.wanted(market.fee_rate):
            continue
        sides = [f"{market.condition_id}:{name}" for name in UPDOWN_SIDES]
        for instrument in sides:
            yield Listing(
                instrument, market.start, kind=KIND_MARKET, resolves_at=market.end
            )
        yield from _prints(market, sides, conv, print_offset)
        for index, instrument in enumerate(sides):
            yield Outcome(
                instrument, market.end, 1.0 if market.winner == index else 0.0
            )


def _prints(
    market: UpDownMarket, sides: Sequence[str], conv: Converter, offset: float
) -> Iterator[Record]:
    for t, outcome, side, price, size, wallet in market.trades:
        at = market.start + t + offset
        if not market.start <= at < market.end or not 0.0 < price <= 1.0:
            conv.stats.skipped[SKIP_PRINT] += 1
            continue
        instrument = sides[outcome]
        yield Reading(instrument, at, price)
        yield TradePrint(
            instrument,
            at,
            wallet or None,
            SIDE_BUY if side > 0 else SIDE_SELL,
            price * size,
        )


# Writing ---------------------------------------------------------------------


@dataclass(frozen=True)
class LaneRowsRequest:
    """What to convert: ``source`` (one of :data:`SOURCES`), ``input`` (a
    file, or for ``updown-history`` the collection folder with ``asset`` and
    ``window``), the optional day range, fee rate and print offset."""

    source: str
    input: str | Path
    asset: str = "btc"
    window: str = "5m"
    start: date | None = None
    end: date | None = None
    fee_rate: float | None = None
    print_offset: float = 0.0

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(
                f"unknown source {self.source!r} (known: {', '.join(SOURCES)})"
            )
        if self.fee_rate is not None and not 0.0 <= self.fee_rate < 1.0:
            raise ValueError("fee_rate must be within [0, 1)")
        if not math.isfinite(self.print_offset):
            raise ValueError("print_offset must be a number of seconds")


def lane_records(request: LaneRowsRequest, conv: Converter) -> Iterator[Record]:
    """The records of a request's input, in market order (the sweep sorts)."""
    if request.source == SOURCE_HISTORY:
        return history_records(load_rows(request.input), conv)
    if request.source == SOURCE_WEATHER:
        return weather_records(load_events(request.input), conv)
    if request.source == SOURCE_FED:
        return fed_records(load_meetings(request.input), conv)
    markets = load_markets(
        request.input,
        request.asset,
        request.window,
        start=request.start,
        end=request.end,
    )
    return updown_records(markets, conv, request.print_offset)


def _open_output(path: Path, compress: bool) -> TextIO:
    if compress:
        return gzip.open(path, "wt", encoding="utf-8")
    return path.open("w", encoding="utf-8")


def _check_input(request: LaneRowsRequest) -> None:
    source = Path(request.input)
    if request.source == SOURCE_UPDOWN:
        folder = source / f"{request.asset}-{request.window}"
        if not folder.is_dir():
            raise ValueError(f"{folder}: no updown-history collection there")
    elif not source.is_file():
        raise ValueError(f"{source}: no such file")


def write_lane_rows(request: LaneRowsRequest, out: str | Path) -> LaneRowStats:
    """Write the request's records as library rows to ``out`` (a new
    ``.jsonl`` or ``.jsonl.gz`` file, written whole or not at all)."""
    target = Path(out)
    if not target.name.endswith(OUTPUT_SUFFIXES):
        raise ValueError(f"{target}: the output must end in .jsonl or .jsonl.gz")
    if target.exists():
        raise ValueError(f"{target} exists already: write to a new file")
    _check_input(request)
    conv = Converter(request.fee_rate)
    partial = target.with_name(target.name + ".partial")
    try:
        with _open_output(partial, target.name.endswith(".gz")) as handle:
            for record in lane_records(request, conv):
                row = to_row(record)
                handle.write(json.dumps(row) + "\n")
                conv.stats.rows[str(row["row"])] += 1
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(target)
    return conv.stats


def describe(stats: LaneRowStats) -> list[str]:
    """The lines ``lane-rows`` prints: rows by kind, fee rates, skips."""
    rows = ", ".join(f"{n} {kind}" for kind, n in sorted(stats.rows.items()))
    rates = ", ".join(f"{rate:g}: {n}" for rate, n in sorted(stats.fee_rates.items()))
    lines = [
        f"{stats.markets} markets written: {rows or 'no rows'}",
        f"markets by fee rate: {rates or 'none'}",
    ]
    lines += [f"skipped {n}: {why}" for why, n in sorted(stats.skipped.items())]
    return lines


__all__ = [
    "KIND_MARKET",
    "Converter",
    "SOURCES",
    "SOURCE_FED",
    "SOURCE_HISTORY",
    "SOURCE_UPDOWN",
    "SOURCE_WEATHER",
    "LaneRowStats",
    "LaneRowsRequest",
    "describe",
    "fed_records",
    "history_records",
    "lane_records",
    "updown_records",
    "weather_records",
    "write_lane_rows",
]
