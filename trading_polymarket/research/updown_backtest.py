"""Replay the late-longshot rule on collected Up/Down trades (FEAT-146, part 2).

The rule, pre-registered in ``docs/dev/PROPOSED-FEATURES.md`` (FEAT-146)
before any run:

* **signal**: the first ``BUY`` print of either outcome at or below ``cap``,
  at or after ``start`` seconds into the window;
* **fill**: the next ``BUY`` print of that outcome in a later second, at that
  print's price, if its notional is at least the stake and its price at most
  ``cap`` + 1 c; otherwise the next such print;
* one entry a market, held to settlement (1 or 0, no fee), the taker fee
  ``0.07 × p(1 − p)`` a share on the entry
  (:class:`~trading_polymarket.fees.FeeSchedule`).

Signal and fill must both come before the window ends (and before ``until``
when a rule has one): the market keeps trading for a while after its window
closes, when the outcome is all but known, and a print then is not one the
rule could have bought at in time.

The pass bar (primary rule only; the others are descriptive): return on
stake after fees above zero in both halves of the days, above zero with the
best 1% of markets by profit removed, and a win rate above the average fill
price at one-sided binomial p < 0.05.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from trading_polymarket.fees import FeeSchedule
from trading_polymarket.research.records import round_trip
from trading_polymarket.research.updown import OUTCOMES, UpDownMarket

STAKE = 5.0
FEE_RATE = 0.07
FILL_SLIP = 0.01
TOP_SHARE = 0.01
P_VALUE = 0.05
STRATEGY = "updown-longshot"
EPSILON = 1e-9

Trade = tuple[float, int, int, float, float, str]


@dataclass(frozen=True)
class Rule:
    """Buy the side at or below ``cap`` from ``start`` seconds (before ``until``)."""

    cap: float
    start: float
    until: float | None = None

    @property
    def name(self) -> str:
        label = f"cap {self.cap * 100:g}c from {self.start:g}s"
        return label if self.until is None else f"{label} until {self.until:g}s"


PRIMARY = Rule(cap=0.05, start=240)
GRID = (
    *(Rule(cap, start) for cap in (0.02, 0.05, 0.10) for start in (180, 240, 270)),
    Rule(cap=0.05, start=0, until=180),
)


@dataclass(frozen=True)
class Entry:
    """One market's entry under one rule, held to settlement."""

    slug: str
    start: float
    end: float
    outcome: int
    signal_t: float
    fill_t: float
    price: float
    won: bool
    stake: float
    fee: float

    @property
    def day(self) -> date:
        return datetime.fromtimestamp(self.start, UTC).date()

    @property
    def shares(self) -> float:
        return self.stake / self.price

    @property
    def profit(self) -> float:
        return (self.shares if self.won else 0.0) - self.stake - self.fee


def _signal(trades: Sequence[Trade], rule: Rule, limit: float) -> Trade | None:
    for trade in trades:
        t, _, side, price, _, _ = trade
        if t >= limit:
            return None
        if t >= rule.start and side == 1 and price <= rule.cap + EPSILON:
            return trade
    return None


def _fillable(trade: Trade, signal: Trade, rule: Rule, stake: float) -> bool:
    t, outcome, side, price, size, _ = trade
    return (
        int(t) > int(signal[0])
        and outcome == signal[1]
        and side == 1
        and price <= rule.cap + FILL_SLIP + EPSILON
        and price * size >= stake - EPSILON
    )


def _fill(
    trades: Sequence[Trade], signal: Trade, rule: Rule, limit: float, stake: float
) -> Trade | None:
    for trade in trades:
        if trade[0] >= limit:
            return None
        if _fillable(trade, signal, rule, stake):
            return trade
    return None


def entry(market: UpDownMarket, rule: Rule, *, stake: float = STAKE) -> Entry | None:
    """The rule's entry in ``market``, or ``None`` when it signals or fills nothing."""
    limit = market.end - market.start
    if rule.until is not None:
        limit = min(limit, rule.until)
    signal = _signal(market.trades, rule, limit)
    if signal is None:
        return None
    fill = _fill(market.trades, signal, rule, limit, stake)
    if fill is None:
        return None
    price = fill[3]
    fee = FeeSchedule(rate=FEE_RATE).taker_fee(stake / price, price)
    return Entry(
        slug=market.slug,
        start=market.start,
        end=market.end,
        outcome=fill[1],
        signal_t=signal[0],
        fill_t=fill[0],
        price=price,
        won=fill[1] == market.winner,
        stake=stake,
        fee=fee,
    )


def replay(
    markets: Iterable[UpDownMarket],
    rules: Sequence[Rule] = GRID,
    *,
    stake: float = STAKE,
) -> tuple[int, dict[Rule, list[Entry]]]:
    """Every rule over every market in one pass: (markets read, entries by rule)."""
    found: dict[Rule, list[Entry]] = {rule: [] for rule in rules}
    count = 0
    for market in markets:
        count += 1
        for rule in rules:
            made = entry(market, rule, stake=stake)
            if made is not None:
                found[rule].append(made)
    return count, found


def binomial_tail(wins: int, n: int, p: float) -> float:
    """``P(X >= wins)`` for ``X ~ Binomial(n, p)``, exactly."""
    if wins <= 0:
        return 1.0
    if p <= 0.0 or wins > n:
        return 0.0
    if p >= 1.0:
        return 1.0
    log_p, log_q = math.log(p), math.log1p(-p)
    total = 0.0
    for k in range(wins, n + 1):
        log_term = (
            math.lgamma(n + 1)
            - math.lgamma(k + 1)
            - math.lgamma(n - k + 1)
            + k * log_p
            + (n - k) * log_q
        )
        total += math.exp(log_term)
    return min(1.0, total)


def roi(entries: Sequence[Entry]) -> float | None:
    """Return on stake after fees; ``None`` with no entries."""
    staked = sum(e.stake for e in entries)
    return sum(e.profit for e in entries) / staked if staked else None


def without_top(entries: Sequence[Entry], share: float = TOP_SHARE) -> list[Entry]:
    """``entries`` without the best ``share`` of them by profit (at least one)."""
    drop = math.ceil(len(entries) * share)
    return sorted(entries, key=lambda e: e.profit)[: len(entries) - drop]


@dataclass(frozen=True)
class Summary:
    rule: Rule
    markets: int
    entries: int
    wins: int
    profit: float
    fees: float
    roi: float | None
    roi_halves: tuple[float | None, float | None]
    roi_without_top: float | None
    average_price: float | None
    win_rate: float | None
    p_value: float | None

    @property
    def passed(self) -> bool:
        checks = (*self.roi_halves, self.roi_without_top)
        if any(value is None or value <= 0 for value in checks):
            return False
        return (
            self.win_rate is not None
            and self.average_price is not None
            and self.win_rate > self.average_price
            and self.p_value is not None
            and self.p_value < P_VALUE
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule.name,
            "markets": self.markets,
            "entries": self.entries,
            "wins": self.wins,
            "profit": round(self.profit, 2),
            "fees": round(self.fees, 2),
            "roi": self.roi,
            "roi_halves": list(self.roi_halves),
            "roi_without_top_1pct": self.roi_without_top,
            "average_price": self.average_price,
            "win_rate": self.win_rate,
            "p_value": self.p_value,
            "passed": self.passed,
        }


def summarise(
    rule: Rule, markets: int, entries: Sequence[Entry], *, split: date
) -> Summary:
    """The pass bar's numbers; ``split`` is the first day of the second half."""
    n = len(entries)
    wins = sum(e.won for e in entries)
    average = sum(e.price for e in entries) / n if n else None
    return Summary(
        rule=rule,
        markets=markets,
        entries=n,
        wins=wins,
        profit=sum(e.profit for e in entries),
        fees=sum(e.fee for e in entries),
        roi=roi(entries),
        roi_halves=(
            roi([e for e in entries if e.day < split]),
            roi([e for e in entries if e.day >= split]),
        ),
        roi_without_top=roi(without_top(entries)),
        average_price=average,
        win_rate=wins / n if n else None,
        p_value=binomial_tail(wins, n, average) if average is not None else None,
    )


def audit_records(entries: Iterable[Entry], rule: Rule) -> list[dict[str, Any]]:
    """The entries as trading-core audit round trips (``trading-core-audit pnl``)."""
    records: list[dict[str, Any]] = []
    for e in entries:
        records.extend(
            round_trip(
                instrument_id=f"{e.slug}:{OUTCOMES[e.outcome]}",
                name=f"{e.slug} {OUTCOMES[e.outcome]}",
                strategy=STRATEGY,
                reason=rule.name,
                entry_time=e.start + e.fill_t,
                entry_price=e.price,
                notional=e.stake,
                entry_fee=e.fee,
                exit_time=e.end,
                exit_price=1.0 if e.won else 0.0,
                metrics={"signal_t": e.signal_t, "fill_t": e.fill_t},
            )
        )
    return records


__all__ = [
    "FEE_RATE",
    "GRID",
    "PRIMARY",
    "STAKE",
    "Entry",
    "Rule",
    "Summary",
    "audit_records",
    "binomial_tail",
    "entry",
    "replay",
    "roi",
    "summarise",
    "without_top",
]
