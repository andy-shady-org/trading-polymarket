"""Replay FEAT-103's expiry fade: late in a window, spot flat, buy the cheap side.

The rule, pre-registered in ``docs/dev/PROPOSED-FEATURES.md`` (FEAT-103,
2026-11-07) before it was run on any data:

* **signal**: the first second ``τ``, from ``first_left`` to ``last_left``
  seconds before the window's end (the last 5 to 1 minutes), at which
  Binance spot moved less than ``flat_bps`` basis points over the
  ``flat_seconds`` before ``τ``, and one outcome's last print at or before
  ``τ`` is at least ``distance`` from 0.50: at or below 0.35 for the fade
  (the cheaper side is bought), at or above 0.65 for its mirror (the dearer
  side is bought; ``favourite``). With both sides past it, the furthest one;
* **fill**: the first ``BUY`` print of that outcome in a later second, from
  ``τ + latency`` to ``τ + latency + 5`` seconds and before the window ends,
  at most 1 c above the price the signal saw, with at least the stake's
  notional, at that print's price; none there, no entry;
* one entry a market, held to settlement, the taker fee ``0.07 × p(1 − p)``
  a share on the entry.

Spot "at ``τ``" is the close of the one-second candle that ended at ``τ``
(:func:`~trading_polymarket.research.updown_stale.spot_path`), so the rule
never sees a second it could not have; print times are the data API's less
``offset`` (FEAT-147's ``ticks-report``).

**Verdict** (the primary rule, the fade at 0.15 from 0.50): PASS when it
passes FEAT-146's bar (return on stake above zero in both halves of the
days and without the best 1% of markets, win rate above the average fill
price at binomial p < 0.05) and the stress rule (3 s latency) does not lose;
INCONCLUSIVE below 200 entries; FAIL otherwise. **Stop rule:** a negative
return after fees ends FEAT-103; a PASS is confirmed on FEAT-101's ticks
before anything else, because minute or print data overstated a taker edge
once.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from trading_polymarket.fees import FeeSchedule
from trading_polymarket.research.updown import UpDownMarket
from trading_polymarket.research.updown_backtest import (
    EPSILON,
    FEE_RATE,
    FILL_SLIP,
    STAKE,
    Entry,
    Summary,
    Trade,
)
from trading_polymarket.research.updown_stale import (
    FILL_SPAN,
    MIN_ENTRIES,
    SpotAt,
    _Prints,
    spot_path,
)

HALF = 0.5


@dataclass(frozen=True)
class FadeRule:
    """Buy the side ``distance`` from 0.50 late in a window with spot flat."""

    favourite: bool = False
    distance: float = 0.15
    first_left: float = 300.0
    last_left: float = 60.0
    flat_bps: float = 6.0
    flat_seconds: int = 60
    latency: float = 0.0

    @property
    def name(self) -> str:
        side = "favourite" if self.favourite else "fade"
        label = (
            f"{side} {self.distance * 100:g}c from 50c, "
            f"{self.first_left:g}-{self.last_left:g}s left"
        )
        if math.isinf(self.flat_bps):
            label += ", any spot"
        else:
            label += f", spot <{self.flat_bps:g}bp/{self.flat_seconds}s"
        return label if not self.latency else f"{label}, {self.latency:g}s late"


PRIMARY = FadeRule()
MIRROR = FadeRule(favourite=True)
STRESS = FadeRule(latency=3.0)
GRID = (
    PRIMARY,
    MIRROR,
    STRESS,
    FadeRule(distance=0.10),
    FadeRule(distance=0.25),
    FadeRule(flat_bps=math.inf),
    FadeRule(favourite=True, distance=0.25),
)


def _flat(path: Sequence[float | None], tau: int, rule: FadeRule) -> bool:
    """Spot moved less than ``flat_bps`` over the ``flat_seconds`` before ``τ``."""
    if math.isinf(rule.flat_bps):
        return True
    if tau < rule.flat_seconds:
        return False
    now, before = path[tau], path[tau - rule.flat_seconds]
    if now is None or before is None:
        return False
    return abs(now - before) / before * 1e4 < rule.flat_bps


def _side(prints: _Prints, tau: int, rule: FadeRule) -> tuple[int, float] | None:
    """The outcome the rule would buy at ``τ`` and the price it saw."""
    found: tuple[int, float] | None = None
    for outcome in (0, 1):
        last = prints.last_at(outcome, tau)
        if last is None:
            continue
        gap = last - HALF if rule.favourite else HALF - last
        if gap >= rule.distance - EPSILON and (
            found is None or abs(last - HALF) > abs(found[1] - HALF)
        ):
            found = (outcome, last)
    return found


def signal(
    market: UpDownMarket,
    rule: FadeRule,
    path: Sequence[float | None],
    prints: _Prints,
) -> tuple[int, int, float] | None:
    """``(τ, outcome, price seen)`` of the rule's signal, or ``None``."""
    length = len(path)
    first = max(0, math.ceil(length - rule.first_left))
    last = math.floor(length - rule.last_left)
    for tau in range(first, last + 1):
        if not _flat(path, tau, rule):
            continue
        side = _side(prints, tau, rule)
        if side is not None:
            return tau, side[0], side[1]
    return None


def _fillable(trade: Trade, outcome: int, cap: float, stake: float) -> bool:
    _, o, side, price, size, _ = trade
    return (
        o == outcome
        and side == 1
        and price <= cap + FILL_SLIP + EPSILON
        and price * size >= stake - EPSILON
    )


def fill(
    market: UpDownMarket,
    rule: FadeRule,
    found: tuple[int, int, float],
    *,
    offset: float,
    stake: float,
) -> tuple[float, Trade] | None:
    """The fill's corrected time and print, or ``None``."""
    tau, outcome, seen = found
    first = tau + rule.latency
    last = min(first + FILL_SPAN, market.end - market.start - EPSILON)
    for trade in market.trades:
        moment = trade[0] - offset
        if moment > last:
            return None
        later = math.floor(moment) > tau
        if (
            later
            and moment >= first - EPSILON
            and _fillable(trade, outcome, seen, stake)
        ):
            return moment, trade
    return None


def entry(
    market: UpDownMarket,
    rule: FadeRule,
    *,
    path: Sequence[float | None],
    prints: _Prints,
    offset: float = 0.0,
    stake: float = STAKE,
) -> Entry | None:
    """The rule's entry in ``market``, or ``None``."""
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
    rules: Sequence[FadeRule] = GRID,
    *,
    offset: float = 0.0,
    stake: float = STAKE,
) -> tuple[int, dict[FadeRule, list[Entry]]]:
    """Every rule over every market in one pass: (markets read, entries by rule)."""
    found: dict[FadeRule, list[Entry]] = {rule: [] for rule in rules}
    count = 0
    for market in markets:
        count += 1
        prints = _Prints.of(market.trades, offset)
        path = spot_path(market, spot)
        for rule in rules:
            made = entry(
                market, rule, path=path, prints=prints, offset=offset, stake=stake
            )
            if made is not None:
                found[rule].append(made)
    return count, found


def verdict(primary: Summary, stress: Summary) -> str:
    """PASS, FAIL or INCONCLUSIVE, as pre-registered (FEAT-147's bar)."""
    if primary.entries < MIN_ENTRIES:
        return "INCONCLUSIVE"
    stress_holds = stress.roi is not None and stress.roi >= 0
    return "PASS" if primary.passed and stress_holds else "FAIL"


__all__ = [
    "GRID",
    "MIRROR",
    "PRIMARY",
    "STRESS",
    "FadeRule",
    "entry",
    "fill",
    "replay",
    "signal",
    "verdict",
]
