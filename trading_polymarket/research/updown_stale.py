"""Replay FEAT-147's rule: buy a cheap side seconds after spot moves its way.

The rule, pre-registered in ``docs/dev/PROPOSED-FEATURES.md`` (FEAT-147)
before the data it is judged on existed:

* **signal**: the first second ``τ`` from ``start`` to the window's end at
  which, for an outcome ``o``, Binance spot is at or past ``threshold`` basis
  points from the window's start price in ``o``'s favour, and ``o``'s last
  print at or before ``τ`` was at or below ``cap``;
* **fill**: the first ``BUY`` print of ``o`` at or below ``cap`` + 1 c with
  at least the stake's notional, in [``τ + latency``, ``τ + latency + 5``]
  seconds, at that print's price; none there, no entry;
* one entry a market, held to settlement, taker fee ``0.07 × p(1 − p)`` a
  share; prints after the window's end are never used.

**Times.** Spot "at ``τ``" is the close of the one-second candle that ended
at ``τ`` (it opened at ``τ − 1``), so no second the rule could not have
seen is used; the start price is the candle that ended at the window's
start. Print times are the data API's, less ``offset``: how far its
timestamp runs after the fill as the market's WebSocket reports it, which
``trading-polymarket ticks-report`` measures.

**Verdict** (the primary rule): PASS when it passes FEAT-146's bar (both
halves, without the best 1%, binomial p < 0.05) and the stress rule (3 s
latency) does not lose; INCONCLUSIVE below 200 entries; FAIL otherwise.
"""

from __future__ import annotations

import bisect
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from trading_polymarket.fees import FeeSchedule
from trading_polymarket.research.updown import SpotDay, UpDownMarket, load_spot
from trading_polymarket.research.updown_backtest import (
    EPSILON,
    FEE_RATE,
    FILL_SLIP,
    STAKE,
    Entry,
    Summary,
)

FILL_SPAN = 5.0
MIN_ENTRIES = 200

SpotAt = Callable[[float], float | None]
Trade = tuple[float, int, int, float, float, str]


@dataclass(frozen=True)
class StaleRule:
    """Buy ``o`` at or below ``cap`` once spot is ``threshold`` bp its way."""

    cap: float = 0.05
    start: float = 240
    threshold: float = -1.5
    latency: float = 2.0

    @property
    def name(self) -> str:
        return (
            f"cap {self.cap * 100:g}c from {self.start:g}s "
            f"spot {self.threshold:+g}bp {self.latency:g}s late"
        )


PRIMARY = StaleRule()
STRESS = StaleRule(latency=3.0)
GRID = (
    PRIMARY,
    StaleRule(latency=1.0),
    STRESS,
    StaleRule(latency=5.0),
    StaleRule(cap=0.03),
    StaleRule(cap=0.10),
    StaleRule(threshold=-4.0),
    StaleRule(threshold=0.0),
    StaleRule(start=120),
)


class SpotSeries:
    """One-second spot across days, read from a backfill folder as needed."""

    def __init__(self, directory: str | Path, symbol: str) -> None:
        self.directory = directory
        self.symbol = symbol
        self._days: dict[date, SpotDay | None] = {}

    def __call__(self, moment: float) -> float | None:
        day = datetime.fromtimestamp(moment, UTC).date()
        if day not in self._days:
            self._days[day] = load_spot(self.directory, self.symbol, day)
        spot = self._days[day]
        return spot.price_at(moment) if spot is not None else None


def distance(price: float, start_price: float, outcome: int) -> float:
    """Basis points from the start price in ``outcome``'s favour (Up is 0)."""
    moved = (price - start_price) / start_price * 1e4
    return moved if outcome == 0 else -moved


@dataclass(frozen=True)
class _Prints:
    """Each outcome's print times (corrected) and prices, in order."""

    times: tuple[list[float], list[float]]
    prices: tuple[list[float], list[float]]

    @classmethod
    def of(cls, trades: Sequence[Trade], offset: float) -> _Prints:
        times: tuple[list[float], list[float]] = ([], [])
        prices: tuple[list[float], list[float]] = ([], [])
        for t, outcome, _, price, _, _ in trades:
            times[outcome].append(t - offset)
            prices[outcome].append(price)
        return cls(times, prices)

    def last_at(self, outcome: int, moment: float) -> float | None:
        index = bisect.bisect_right(self.times[outcome], moment) - 1
        return self.prices[outcome][index] if index >= 0 else None


def _qualifies(
    rule: StaleRule, prints: _Prints, outcome: int, moved: float, tau: float
) -> bool:
    if moved < rule.threshold - EPSILON:
        return False
    last = prints.last_at(outcome, tau)
    return last is not None and last <= rule.cap + EPSILON


def spot_path(market: UpDownMarket, spot: SpotAt) -> list[float | None]:
    """Spot known at each second ``τ`` of the window (``path[0]``: the start)."""
    length = int(market.end - market.start)
    return [spot(market.start + tau - 1) for tau in range(length)]


def signal(
    market: UpDownMarket,
    rule: StaleRule,
    path: Sequence[float | None],
    prints: _Prints,
) -> tuple[int, int] | None:
    """``(τ, outcome)`` of the rule's signal in ``market``, or ``None``."""
    start_price = path[0] if path else None
    if start_price is None:
        return None
    for tau in range(int(rule.start), len(path)):
        price = path[tau]
        if price is None:
            continue
        for outcome in (0, 1):
            moved = distance(price, start_price, outcome)
            if _qualifies(rule, prints, outcome, moved, tau):
                return tau, outcome
    return None


def _fillable(trade: Trade, outcome: int, rule: StaleRule, stake: float) -> bool:
    _, o, side, price, size, _ = trade
    return (
        o == outcome
        and side == 1
        and price <= rule.cap + FILL_SLIP + EPSILON
        and price * size >= stake - EPSILON
    )


def fill(
    market: UpDownMarket,
    rule: StaleRule,
    found: tuple[int, int],
    *,
    offset: float,
    stake: float,
) -> tuple[float, Trade] | None:
    """The fill's corrected time and print, or ``None``."""
    tau, outcome = found
    first = tau + rule.latency
    last = min(first + FILL_SPAN, market.end - market.start - EPSILON)
    for trade in market.trades:
        moment = trade[0] - offset
        if moment > last:
            return None
        if moment >= first - EPSILON and _fillable(trade, outcome, rule, stake):
            return moment, trade
    return None


def entry(
    market: UpDownMarket,
    rule: StaleRule,
    spot: SpotAt,
    *,
    offset: float = 0.0,
    stake: float = STAKE,
    prints: _Prints | None = None,
    path: Sequence[float | None] | None = None,
) -> Entry | None:
    """The rule's entry in ``market``, or ``None``."""
    prints = prints or _Prints.of(market.trades, offset)
    path = spot_path(market, spot) if path is None else path
    found = signal(market, rule, path, prints)
    if found is None:
        return None
    filled = fill(market, rule, found, offset=offset, stake=stake)
    if filled is None:
        return None
    moment, trade = filled
    price = trade[3]
    return Entry(
        slug=market.slug,
        start=market.start,
        end=market.end,
        outcome=found[1],
        signal_t=found[0],
        fill_t=moment,
        price=price,
        won=found[1] == market.winner,
        stake=stake,
        fee=FeeSchedule(rate=FEE_RATE).taker_fee(stake / price, price),
    )


def replay(
    markets: Iterable[UpDownMarket],
    spot: SpotAt,
    rules: Sequence[StaleRule] = GRID,
    *,
    offset: float = 0.0,
    stake: float = STAKE,
) -> tuple[int, dict[StaleRule, list[Entry]]]:
    """Every rule over every market in one pass: (markets read, entries by rule)."""
    found: dict[StaleRule, list[Entry]] = {rule: [] for rule in rules}
    count = 0
    for market in markets:
        count += 1
        prints = _Prints.of(market.trades, offset)
        path = spot_path(market, spot)
        for rule in rules:
            made = entry(
                market,
                rule,
                spot,
                offset=offset,
                stake=stake,
                prints=prints,
                path=path,
            )
            if made is not None:
                found[rule].append(made)
    return count, found


def verdict(primary: Summary, stress: Summary) -> str:
    """PASS, FAIL or INCONCLUSIVE, as pre-registered."""
    if primary.entries < MIN_ENTRIES:
        return "INCONCLUSIVE"
    stress_holds = stress.roi is not None and stress.roi >= 0
    return "PASS" if primary.passed and stress_holds else "FAIL"


__all__ = [
    "FILL_SPAN",
    "GRID",
    "MIN_ENTRIES",
    "PRIMARY",
    "STRESS",
    "SpotSeries",
    "StaleRule",
    "distance",
    "entry",
    "fill",
    "replay",
    "signal",
    "spot_path",
    "verdict",
]
