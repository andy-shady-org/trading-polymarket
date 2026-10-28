"""Caches of markets (by token id) and order books, shared by every component.

One cycle asks for the same market and book several times (scout, filters,
analyst, execution, marking); the caches make that one request. Execution
always asks for a fresh book (``max_age=0``): a fill is never simulated on a
stale price (pumpfun "No Read, No Fill").
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable

from trading_polymarket.book import OrderBook
from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.markets import Market


class MarketCatalogue:
    def __init__(
        self,
        gamma: GammaClient,
        *,
        ttl: float = 120.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.gamma = gamma
        self.ttl = ttl
        self.clock = clock
        self._by_token: dict[str, tuple[Market, float]] = {}

    def __len__(self) -> int:
        return len({m.market_id for m, _ in self._by_token.values()})

    def put(self, markets: Iterable[Market]) -> None:
        now = self.clock()
        for market in markets:
            for token in market.token_ids:
                self._by_token[token] = (market, now)

    def cached(self, token_id: str) -> Market | None:
        entry = self._by_token.get(token_id)
        return entry[0] if entry else None

    async def get(
        self, token_id: str, *, max_age: float | None = None
    ) -> Market | None:
        """The market owning ``token_id``; refetched when older than ``max_age``."""
        age_limit = self.ttl if max_age is None else max_age
        entry = self._by_token.get(token_id)
        if entry is not None and self.clock() - entry[1] < age_limit:
            return entry[0]
        market = await self.gamma.market_by_token(token_id)
        if market is None:
            return entry[0] if entry else None
        self.put([market])
        return market

    async def refresh(self, token_ids: Iterable[str]) -> None:
        self.put(await self.gamma.markets_by_tokens(token_ids))


class BookCache:
    def __init__(
        self,
        clob: ClobClient,
        *,
        ttl: float = 5.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.clob = clob
        self.ttl = ttl
        self.clock = clock
        self._books: dict[str, tuple[OrderBook, float]] = {}

    def cached(self, token_id: str) -> OrderBook | None:
        entry = self._books.get(token_id)
        return entry[0] if entry else None

    def forget(self, token_id: str) -> None:
        self._books.pop(token_id, None)

    async def get(self, token_id: str, *, max_age: float | None = None) -> OrderBook:
        age_limit = self.ttl if max_age is None else max_age
        entry = self._books.get(token_id)
        if entry is not None and self.clock() - entry[1] < age_limit:
            return entry[0]
        book = await self.clob.book(token_id)
        self._books[token_id] = (book, self.clock())
        return book


__all__ = ["BookCache", "MarketCatalogue"]
