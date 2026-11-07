"""Full sets of a neg-risk event, priced on their books (FEAT-102; no orders, ever).

In a neg-risk event (``negRisk``) exactly one outcome wins, so:

* **a Yes set** - one Yes share of every live outcome - pays exactly 1;
* **a No set** - one No share of every live outcome - pays ``n - 1`` for
  ``n`` live outcomes (every outcome but the winner pays 1).

A set is a gap when it costs less than it pays, fees included. Binary Yes +
No pairs are not checked: a binary market's No book is its Yes book
mirrored (No ask = 1 - Yes bid, at the same size; 39 of 39 markets on
2026-11-07), so a pair costs 1 plus the spread and is never below 1. For the
same reason only Yes books are read: a No set's legs are walked on the Yes
bids.

**A set is only complete when every outcome is in it** (TP-13): each of the
event's markets must be tradable, or closed and resolved No. A market closed
without a result, inactive (in an event that is not augmented), malformed,
or resolved Yes (the event is decided) leaves no set at all: buying the
outcomes that happen to be open would not be a full set. In an augmented
event (``negRiskAugmented``, with an "Other" outcome, ``negRiskOther``,
standing for names not yet listed) unlisted placeholder markets (inactive,
not closed) are left out, but only when "Other" itself is tradable: until it
is, the listed names are only part of the field (on 2026-11-07, 3,830 of
14,532 sets, some priced at 12 c for the set). Augmented sets are flagged
``augmented``: a name added later can win without paying them.

**Depth:** each leg's ladder is its book's levels with the taker fee per
share added (``FeeSchedule.per_share`` at the level's price). Walking the
legs together gives the marginal cost of each further set; it never falls,
so the sets worth buying are a prefix:

* ``best_cost`` - the cheapest set (every leg's best level);
* ``cost_10`` / ``cost_50`` / ``cost_100`` - the total cost of that many sets,
  ``None`` when a leg is too thin;
* ``max_size`` / ``max_profit`` - the most sets each earning at least
  ``min_profit`` after fees, and their total profit;
* ``min_order`` - the largest minimum order size of the legs (a leg cannot be
  bought below it).

A set is **open** (a gap) when ``max_size`` reaches ``min_order`` (and at
least one set). trading-core opens one instrument per signal, so these are
measured, not traded: ``trading-polymarket arb`` (``research/arb_loop.py``)
records them, and ``arb-report`` (``research/arb_report.py``) judges them
against FEAT-102's rule (``docs/dev/runs/arb-1.md``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from trading_polymarket.book import Level, OrderBook
from trading_polymarket.markets import Market, markets_from_event

KIND_YES = "yes_set"
KIND_NO = "no_set"
KINDS = (KIND_YES, KIND_NO)
DEFAULT_MIN_PROFIT = 0.005
DEPTHS = (10, 50, 100)
_EPS = 1e-9


@dataclass(frozen=True)
class SetSpec:
    """One full set of an event: its live markets, read on their Yes books."""

    kind: str
    event_id: str
    slug: str
    title: str
    tags: tuple[str, ...]
    augmented: bool
    markets: tuple[Market, ...]

    @property
    def key(self) -> str:
        return f"{self.event_id}:{self.kind}"

    @property
    def payout(self) -> float:
        return 1.0 if self.kind == KIND_YES else float(len(self.markets) - 1)

    @property
    def tokens(self) -> tuple[str, ...]:
        return tuple(m.yes_token for m in self.markets)

    def row(self) -> dict[str, Any]:
        """What a gap's record says about its set."""
        return {
            "key": self.key,
            "kind": self.kind,
            "event_id": self.event_id,
            "slug": self.slug,
            "title": self.title,
            "tags": list(self.tags),
            "augmented": self.augmented,
            "legs": len(self.markets),
            "payout": self.payout,
            "tokens": list(self.tokens),
            "fee_legs": sum(not m.fee.free for m in self.markets),
        }


def _settled_no(market: Market) -> bool:
    return market.resolved and market.outcome_prices[0] == 0.0


def _left_out(market: Market, augmented: bool) -> bool:
    """A market a full set does not need: resolved No, or an augmented
    event's unlisted placeholder."""
    if market.closed:
        return _settled_no(market)
    return augmented and not market.active


def live_markets(
    raw_count: int, markets: Sequence[Market], *, augmented: bool
) -> tuple[Market, ...] | None:
    """The markets a full set buys, or ``None`` when no full set exists
    (see the module docstring, TP-13). ``raw_count`` is how many markets the
    event listed: one that could not be parsed is an outcome we cannot buy."""
    if raw_count != len(markets) or not all(m.neg_risk for m in markets):
        return None
    live: list[Market] = []
    for market in markets:
        if market.tradable:
            live.append(market)
        elif not _left_out(market, augmented):
            return None
    return tuple(live) if len(live) >= 2 else None


def _other_tradable(raw: Sequence[Mapping[str, Any]]) -> bool:
    """An augmented event's "Other" market accepts orders."""
    return any(
        m.get("negRiskOther")
        and m.get("active")
        and not m.get("closed")
        and m.get("acceptingOrders")
        for m in raw
    )


def event_sets(
    event: Mapping[str, Any], markets: Sequence[Market] | None = None
) -> list[SetSpec]:
    """The Yes set and the No set of a neg-risk event (none when it has no
    full set). ``markets`` are the event's parsed markets (parsed here when
    not given)."""
    raw = [m for m in event.get("markets") or [] if isinstance(m, Mapping)]
    parsed = markets_from_event(event) if markets is None else list(markets)
    augmented = bool(event.get("negRiskAugmented"))
    if not event.get("negRisk", True) or (augmented and not _other_tradable(raw)):
        return []
    live = live_markets(len(raw), parsed, augmented=augmented)
    if live is None:
        return []
    tags = live[0].tags
    return [
        SetSpec(
            kind=kind,
            event_id=str(event.get("id") or ""),
            slug=str(event.get("slug") or ""),
            title=str(event.get("title") or ""),
            tags=tags,
            augmented=augmented,
            markets=live,
        )
        for kind in KINDS
    ]


def ladder(kind: str, market: Market, book: OrderBook) -> list[Level]:
    """One leg's levels, cheapest first, as cost per share with the fee: a
    Yes leg's asks, or a No leg's asks read off the Yes bids (``1 - bid``)."""
    if kind == KIND_YES:
        prices = [(level.price, level.size) for level in book.asks]
    else:
        prices = [(1.0 - level.price, level.size) for level in book.bids]
    return [Level(p + market.fee.per_share(p), size) for p, size in prices]


def steps(ladders: Sequence[Sequence[Level]]) -> list[Level]:
    """Walk every leg at once: ``(sets, marginal cost of each)``, in order,
    until a leg runs out (marginal costs never fall)."""
    if not ladders or any(not lad for lad in ladders):
        return []
    index = [0] * len(ladders)
    left = [lad[0].size for lad in ladders]
    walked: list[Level] = []
    while all(i < len(lad) for i, lad in zip(index, ladders, strict=True)):
        take = min(left)
        cost = sum(lad[i].price for i, lad in zip(index, ladders, strict=True))
        walked.append(Level(cost, take))
        for leg, lad in enumerate(ladders):
            left[leg] -= take
            if left[leg] <= _EPS:
                index[leg] += 1
                left[leg] = lad[index[leg]].size if index[leg] < len(lad) else 0.0
    return walked


def cost_of(walked: Sequence[Level], sets: float) -> float | None:
    """The total cost of ``sets`` sets, or ``None`` when the books are thinner."""
    total, need = 0.0, sets
    for step in walked:
        take = min(need, step.size)
        total += take * step.price
        need -= take
        if need <= _EPS:
            return total
    return None


@dataclass(frozen=True)
class SetQuote:
    """A set priced on one read of its books (see the module docstring)."""

    key: str
    best_cost: float | None
    max_size: float
    max_profit: float
    depth: float
    costs: tuple[float | None, ...]  # for DEPTHS sets
    min_order: float
    open: bool

    def best_profit(self, payout: float) -> float | None:
        return None if self.best_cost is None else payout - self.best_cost

    def row(self, payout: float) -> dict[str, Any]:
        best = self.best_profit(payout)
        return {
            "best_cost": _round(self.best_cost),
            "best_profit": _round(best),
            "max_size": round(self.max_size, 4),
            "max_profit": round(self.max_profit, 5),
            "depth": round(self.depth, 4),
            **{f"cost_{n}": _round(c) for n, c in zip(DEPTHS, self.costs, strict=True)},
            "min_order": self.min_order,
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def quote(
    spec: SetSpec, books: Mapping[str, OrderBook], *, min_profit: float
) -> SetQuote | None:
    """``spec`` priced on ``books`` (by Yes token); ``None`` when a leg's
    book is missing."""
    legs = [books.get(token) for token in spec.tokens]
    if any(book is None for book in legs):
        return None
    read = [book for book in legs if book is not None]
    walked = steps(
        [ladder(spec.kind, m, b) for m, b in zip(spec.markets, read, strict=True)]
    )
    worth = [s for s in walked if spec.payout - s.price >= min_profit - _EPS]
    max_size = sum(s.size for s in worth)
    min_order = max(
        [
            1.0,
            *(
                b.min_order_size or m.min_order_size
                for m, b in zip(spec.markets, read, strict=True)
            ),
        ]
    )
    return SetQuote(
        key=spec.key,
        best_cost=walked[0].price if walked else None,
        max_size=max_size,
        max_profit=sum(s.size * (spec.payout - s.price) for s in worth),
        depth=sum(s.size for s in walked),
        costs=tuple(cost_of(walked, n) for n in DEPTHS),
        min_order=min_order,
        open=max_size >= min_order - _EPS,
    )


def leg_levels(
    spec: SetSpec, books: Mapping[str, OrderBook], *, levels: int = 5
) -> list[list[list[float]]]:
    """Each leg's first ``levels`` ladder levels before the fee
    ``[[price, size], ...]``, for an observation's record."""
    out: list[list[list[float]]] = []
    for token in spec.tokens:
        book = books.get(token)
        side: Iterable[Level] = ()
        if book is not None:
            if spec.kind == KIND_YES:
                side = book.asks
            else:
                side = (Level(round(1.0 - lv.price, 6), lv.size) for lv in book.bids)
        out.append([[lv.price, lv.size] for lv in list(side)[:levels]])
    return out


__all__ = [
    "DEFAULT_MIN_PROFIT",
    "DEPTHS",
    "KINDS",
    "KIND_NO",
    "KIND_YES",
    "SetQuote",
    "SetSpec",
    "cost_of",
    "event_sets",
    "ladder",
    "leg_levels",
    "live_markets",
    "quote",
    "steps",
]
