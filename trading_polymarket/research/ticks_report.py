"""Read a ``ticks`` recording: are we fast enough for FEAT-147?

``trading-polymarket ticks-report`` answers part 1 of FEAT-147 from what
``trading-polymarket ticks`` recorded (:mod:`trading_polymarket.research.ticks`):

* **Binance's receive delay**: ``rx`` less the trade's own time. It includes
  any difference between this computer's clock and Binance's, so keep the
  clock synchronised (macOS does by default);
* **the round trip** to the CLOB's host, the floor under an order's trip;
* **the data API's timestamp offset**: the data API's ``timestamp`` less the
  fill's time on the market WebSocket, matched by transaction hash for
  markets already over (fetched from the data API). Its median is
  ``updown-backtest --rule stale --timestamp-offset``;
* **stale asks**: FEAT-147's signals as they happened. In the last minute
  (from 240 s), the first Binance trade at which spot is at or past −1.5 bp
  from the window's start price in an outcome's favour while that outcome's
  best ask is at or below 6 c (the rule's cap plus its 1 c slip). The ask's
  **lifetime** runs from that Binance trade until the best ask is above the
  signal's ask or gone (to the window's end when it never goes: censored);
  **our delay** is the Binance trade's receive delay plus the nearest round
  trip. A signal is takeable when the ask outlives our delay.

**Decision** (pre-registered): the lead is takeable when, over at least
three days of recording, at least half of the signals are takeable.
"""

from __future__ import annotations

import bisect
import gzip
import json
import statistics
import zlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from trading_polymarket.clients.data_api import DataApiClient, TradePrint
from trading_polymarket.research.updown_stale import distance

CAP = 0.05
SLIP = 0.01
THRESHOLD = -1.5
FROM_SECONDS = 240
MIN_DAYS = 3
TAKEABLE_SHARE = 0.5


def _rows(path: Path) -> Iterator[Any]:
    """Every JSON row of a recorded file; a file still being written ends early."""
    if not path.is_file():
        return
    opener: Any = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except (EOFError, OSError, zlib.error):
        return


@dataclass
class Quotes:
    """One token's best ask over time, by receive time."""

    rx: list[int] = field(default_factory=list)
    ask: list[float | None] = field(default_factory=list)

    def at(self, moment: int) -> tuple[int, float | None]:
        """(index, best ask) of the last quote received at or before ``moment``."""
        index = bisect.bisect_right(self.rx, moment) - 1
        return index, self.ask[index] if index >= 0 else None

    def gone(self, index: int, ask: float, until: int) -> int | None:
        """When, after ``index``, the best ask is above ``ask`` or gone."""
        for i in range(index + 1, len(self.rx)):
            if self.rx[i] >= until:
                return None
            later = self.ask[i]
            if later is None or later > ask:
                return self.rx[i]
        return None


@dataclass
class Recording:
    days: list[str] = field(default_factory=list)
    spot: list[tuple[int, int, float]] = field(default_factory=list)
    quotes: dict[str, Quotes] = field(default_factory=dict)
    trades: list[list[Any]] = field(default_factory=list)
    probes: list[tuple[int, float | None]] = field(default_factory=list)
    markets: dict[int, Mapping[str, Any]] = field(default_factory=dict)


def _in_range(name: str, start: date | None, end: date | None) -> bool:
    try:
        day = date.fromisoformat(name)
    except ValueError:
        return False
    return (start is None or day >= start) and (end is None or day < end)


def _add_day(recording: Recording, folder: Path) -> None:
    for row in _rows(folder / "spot.jsonl.gz"):
        recording.spot.append((int(row[0]), int(row[2]), float(row[3])))
    for row in _rows(folder / "quotes.jsonl.gz"):
        quotes = recording.quotes.setdefault(str(row[2]), Quotes())
        quotes.rx.append(int(row[0]))
        quotes.ask.append(row[5])
    recording.trades.extend(_rows(folder / "trades.jsonl.gz"))
    for row in _rows(folder / "probes.jsonl"):
        recording.probes.append((int(row[0]), row[1]))
    for row in _rows(folder / "markets.jsonl"):
        recording.markets[int(row["start"])] = row


def load_recording(
    directory: str | Path, *, start: date | None = None, end: date | None = None
) -> Recording:
    """The recording's days in ``[start, end)``, each stream in time order."""
    recording = Recording()
    root = Path(directory)
    folders = sorted(root.iterdir()) if root.is_dir() else []
    for folder in folders:
        if folder.is_dir() and _in_range(folder.name, start, end):
            recording.days.append(folder.name)
            _add_day(recording, folder)
    recording.spot.sort(key=lambda row: row[1])
    recording.probes.sort()
    return recording


def quantiles(values: Sequence[float]) -> dict[str, float] | None:
    """``n`` and the 10th, 50th and 90th percentiles; ``None`` when empty."""
    if not values:
        return None
    ordered = sorted(values)

    def pick(share: float) -> float:
        return ordered[min(len(ordered) - 1, int(share * len(ordered)))]

    return {"n": len(ordered), "p10": pick(0.1), "p50": pick(0.5), "p90": pick(0.9)}


def receive_delays(recording: Recording) -> list[float]:
    return [float(rx - trade_time) for rx, trade_time, _ in recording.spot]


def round_trips(recording: Recording) -> list[float]:
    return [float(rtt) for _, rtt in recording.probes if rtt is not None]


def nearest_round_trip(recording: Recording, moment: int) -> float | None:
    """The round trip measured nearest ``moment`` (failed probes skipped)."""
    timed = [(rx, rtt) for rx, rtt in recording.probes if rtt is not None]
    if not timed:
        return None
    index = bisect.bisect_left([rx for rx, _ in timed], moment)
    near = [timed[i] for i in (index - 1, index) if 0 <= i < len(timed)]
    return float(min(near, key=lambda probe: abs(probe[0] - moment))[1])


@dataclass(frozen=True)
class Signal:
    window: int
    outcome: int
    trade_time: int
    received: int
    ask: float
    lifetime: int
    censored: bool
    delay: float | None

    @property
    def takeable(self) -> bool:
        return self.delay is not None and self.lifetime > self.delay


def _start_price(recording: Recording, times: list[int], window: int) -> float | None:
    index = bisect.bisect_right(times, window * 1000) - 1
    return recording.spot[index][2] if index >= 0 else None


def _signal(
    recording: Recording,
    window: int,
    length: int,
    outcome: int,
    spot: tuple[int, int, float],
    start_price: float,
) -> Signal | None:
    received, trade_time, price = spot
    if distance(price, start_price, outcome) < THRESHOLD - 1e-9:
        return None
    quotes = recording.quotes.get(f"{window}:{outcome}")
    if quotes is None:
        return None
    index, ask = quotes.at(received)
    if ask is None or ask > CAP + SLIP + 1e-9:
        return None
    end = (window + length) * 1000
    gone = quotes.gone(index, ask, end)
    round_trip = nearest_round_trip(recording, received)
    return Signal(
        window=window,
        outcome=outcome,
        trade_time=trade_time,
        received=received,
        ask=ask,
        lifetime=(gone if gone is not None else end) - trade_time,
        censored=gone is None,
        delay=None if round_trip is None else received - trade_time + round_trip,
    )


def _window_signals(
    recording: Recording, times: list[int], window: int, length: int
) -> list[Signal]:
    start_price = _start_price(recording, times, window)
    if start_price is None:
        return []
    found: dict[int, Signal] = {}
    first = bisect.bisect_left(times, (window + FROM_SECONDS) * 1000)
    last = bisect.bisect_left(times, (window + length) * 1000)
    for spot in recording.spot[first:last]:
        for outcome in (0, 1):
            if outcome not in found:
                made = _signal(recording, window, length, outcome, spot, start_price)
                if made is not None:
                    found[outcome] = made
    return list(found.values())


def signals(recording: Recording, *, length: int = 300) -> list[Signal]:
    """FEAT-147's signals in every recorded window, first per outcome."""
    times = [row[1] for row in recording.spot]
    found: list[Signal] = []
    for window in sorted(recording.markets):
        found.extend(_window_signals(recording, times, window, length))
    return found


def decision(days: int, found: Sequence[Signal]) -> str:
    """The pre-registered decision on part 1."""
    if days < MIN_DAYS:
        return f"not enough days ({days} of {MIN_DAYS})"
    if not found:
        return "no signals"
    share = sum(s.takeable for s in found) / len(found)
    return "takeable" if share >= TAKEABLE_SHARE else "not takeable"


def match_offsets(
    trades: Sequence[Sequence[Any]], prints: Sequence[TradePrint]
) -> list[float]:
    """Data API time less the WebSocket's fill time, per matched transaction."""
    first: dict[str, int] = {}
    for row in trades:
        tx, server = str(row[6] or ""), row[1]
        if tx and isinstance(server, int):
            first[tx] = min(server, first.get(tx, server))
    return [
        p.timestamp - first[p.transaction_hash] / 1000
        for p in prints
        if p.transaction_hash in first
    ]


async def fetch_offsets(
    recording: Recording, data: DataApiClient, *, markets: int, now: float
) -> list[float]:
    """Offsets for up to ``markets`` recorded markets already over."""
    starts = {int(str(row[2]).split(":")[0]) for row in recording.trades}
    over = [
        recording.markets[s]
        for s in sorted(starts)
        if s in recording.markets and recording.markets[s]["end"] < now
    ][:markets]
    found: list[float] = []
    for market in over:
        prints = await data.trades(str(market["condition_id"]))
        found.extend(match_offsets(recording.trades, prints))
    return found


def median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


__all__ = [
    "Quotes",
    "Recording",
    "Signal",
    "decision",
    "fetch_offsets",
    "load_recording",
    "match_offsets",
    "median",
    "nearest_round_trip",
    "quantiles",
    "receive_delays",
    "round_trips",
    "signals",
]
