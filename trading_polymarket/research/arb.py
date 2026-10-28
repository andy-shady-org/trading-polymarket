"""Record-only scanner for structural arbitrage (no orders, ever).

Two shapes are checked on the live books:

* **binary pair** - buying both Yes and No of one market costs
  ``ask_yes + ask_no`` plus fees and pays exactly 1 at resolution;
* **neg-risk set** - in a mutually exclusive event (``negRisk``) exactly one
  Yes wins, so buying every Yes costs ``sum(asks)`` plus fees and pays 1.

An opportunity is recorded when the cost is below ``1 - min_profit`` for at
least ``min_size`` shares on every leg. trading-core opens one instrument per
signal, so multi-leg trades cannot be executed atomically through the engine;
the scanner's JSONL (``data/arb.jsonl``) measures how often, how large and how
long these gaps are, which decides whether a dedicated executor is worth
building (docs/STRATEGIES.md, docs/dev/TODO.md). Augmented neg-risk events
(with an "Other" placeholder) are flagged: their Yes set may be incomplete.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from trading_polymarket.book import OrderBook
from trading_polymarket.catalogue import BookCache
from trading_polymarket.clients.clob import BookUnavailable
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.markets import Market

KIND_PAIR = "binary_pair"
KIND_SET = "neg_risk_set"


@dataclass(frozen=True)
class Opportunity:
    kind: str
    title: str
    legs: int
    cost: float  # per set of shares, fees included
    profit: float  # per set: 1 - cost
    size: float  # sets available on the thinnest leg at the best asks
    augmented: bool
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _leg_cost(book: OrderBook, market: Market) -> tuple[float, float] | None:
    if not book.asks:
        return None
    best = book.asks[0]
    return best.price + market.fee.per_share(best.price), best.size


def _evaluate(
    kind: str,
    title: str,
    legs: Sequence[tuple[OrderBook, Market]],
    *,
    augmented: bool,
    min_profit: float,
    min_size: float,
    now: float,
) -> Opportunity | None:
    priced = [_leg_cost(book, market) for book, market in legs]
    if not priced or any(p is None for p in priced):
        return None
    costs = [p for p in priced if p is not None]
    cost = sum(c for c, _ in costs)
    size = min(s for _, s in costs)
    if 1.0 - cost < min_profit or size < min_size:
        return None
    return Opportunity(
        kind, title, len(legs), round(cost, 5), round(1 - cost, 5), size, augmented, now
    )


class ArbScanner:
    def __init__(
        self,
        gamma: GammaClient,
        books: BookCache,
        *,
        min_profit: float = 0.005,
        min_size: float = 5.0,
        prefilter: float = 0.02,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.gamma = gamma
        self.books = books
        self.min_profit = min_profit
        self.min_size = min_size
        self.prefilter = prefilter
        self.clock = clock

    async def _books(self, tokens: Sequence[str]) -> list[OrderBook]:
        """Every leg's book, or none at all when one leg has no book."""
        try:
            return list(await asyncio.gather(*(self.books.get(t) for t in tokens)))
        except BookUnavailable:
            return []

    async def scan(self, *, max_pages: int = 5) -> list[Opportunity]:
        found: list[Opportunity] = []
        now = self.clock()
        for event, markets in await self.gamma.events(
            max_pages=max_pages, closed=False, order="volume24hr", ascending=False
        ):
            title = str(event.get("title") or "")
            live = [m for m in markets if m.tradable and len(m.token_ids) == 2]
            # Gamma's quotes pre-screen; only near-misses cost book reads.
            for market in live:
                if market.best_ask is None or market.best_bid is None:
                    continue
                if market.best_ask + (1 - market.best_bid) > 1 + self.prefilter:
                    continue
                books = await self._books(market.token_ids)
                opportunity = _evaluate(
                    KIND_PAIR,
                    market.question,
                    [(book, market) for book in books],
                    augmented=False,
                    min_profit=self.min_profit,
                    min_size=self.min_size,
                    now=now,
                )
                if opportunity is not None:
                    found.append(opportunity)
            if len(live) < 2 or not all(m.neg_risk for m in live):
                continue
            asks = [m.best_ask for m in live]
            if any(a is None for a in asks) or sum(a or 0 for a in asks) > (
                1 + self.prefilter
            ):
                continue
            books = await self._books([m.yes_token for m in live])
            opportunity = _evaluate(
                KIND_SET,
                title,
                list(zip(books, live, strict=False)),
                augmented=bool(event.get("negRiskAugmented")),
                min_profit=self.min_profit,
                min_size=self.min_size,
                now=now,
            )
            if opportunity is not None:
                found.append(opportunity)
        found.sort(key=lambda o: o.profit, reverse=True)
        return found


__all__ = ["ArbScanner", "KIND_PAIR", "KIND_SET", "Opportunity"]
