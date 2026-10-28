"""Turning orders into fills.

:class:`PaperExecutor` simulates a marketable (FOK-style taker) order against
the **live** order book:

* a buy spends at most the order's notional on asks priced at or below its
  limit (default: best ask + ``max_slippage``, never above ``price_cap``);
* a sell sells at most the order's size into bids at or above its limit
  (default: best bid - ``max_slippage``); a partial fill is reported as such;
* shares are rounded **down** to the venue's precision (2 decimals);
* each level pays the market's taker fee, ``shares x rate x p(1 - p)``,
  recorded as the ``fee`` cost component (docs/ACCOUNTING in trading-core);
* orders below the market's minimum size or ``min_notional`` are refused, as
  are closed, paused or unknown markets - a paper fill must never succeed
  where a live one would not (pumpfun BUG-145/152);
* a sell of a token whose market has **resolved** redeems at the payout (1 for
  the winner, 0 for the loser) with no fee.

:class:`LiveExecutor` refuses everything: live order signing (CLOB V2, pUSD,
``py-clob-client-v2``, a funded proxy wallet) is a later, gated step
(docs/LIVE-TRADING.md, docs/GO-NO-GO.md stage 2).
"""

from __future__ import annotations

import itertools
import math
import time
from collections.abc import Callable
from typing import Any

from trading_core.module.base import (
    COST_SOURCE_MODELLED,
    ExecutionRefused,
    Fill,
    OrderRequest,
    Side,
    TradeCosts,
)

from trading_polymarket.book import Level, OrderBook, Walk
from trading_polymarket.catalogue import BookCache, MarketCatalogue
from trading_polymarket.clients.clob import BookUnavailable
from trading_polymarket.clients.http import HttpError
from trading_polymarket.config import PaperSettings
from trading_polymarket.fees import FeeSchedule
from trading_polymarket.markets import Market

REASON_RESOLVED = "resolved"
_counter = itertools.count(1)


def floor_to(value: float, decimals: int) -> float:
    factor = 10**decimals
    return math.floor(value * factor + 1e-9) / factor


def trim_walk(walk: Walk, size: float) -> Walk:
    """``walk`` cut to ``size`` units (taken from the worst levels first)."""
    parts: list[Level] = []
    remaining = size
    for part in walk.parts:
        if remaining <= 0:
            break
        take = min(part.size, remaining)
        parts.append(Level(part.price, take))
        remaining -= take
    return Walk(
        size=sum(p.size for p in parts),
        notional=sum(p.size * p.price for p in parts),
        parts=tuple(parts),
    )


def walk_fee(walk: Walk, schedule: FeeSchedule) -> float:
    return round(sum(schedule.taker_fee(p.size, p.price) for p in walk.parts), 5)


def _reference(prefix: str) -> str:
    return f"paper-{prefix}-{int(time.time() * 1000)}-{next(_counter)}"


class PaperExecutor:
    def __init__(
        self,
        catalogue: MarketCatalogue,
        books: BookCache,
        settings: PaperSettings,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.catalogue = catalogue
        self.books = books
        self.settings = settings
        self.clock = clock

    async def _market(self, token_id: str, *, max_age: float | None) -> Market:
        try:
            market = await self.catalogue.get(token_id, max_age=max_age)
        except HttpError as exc:
            raise ExecutionRefused(f"market lookup failed: {exc}") from exc
        if market is None:
            raise ExecutionRefused(f"unknown token {token_id}")
        return market

    async def _book(self, token_id: str) -> OrderBook:
        try:
            return await self.books.get(token_id, max_age=0.0)
        except BookUnavailable as exc:
            raise ExecutionRefused(str(exc)) from exc
        except HttpError as exc:
            raise ExecutionRefused(f"order book read failed: {exc}") from exc

    def _metadata(self, market: Market, token_id: str, **extra: Any) -> dict[str, Any]:
        return {
            "market_id": market.market_id,
            "condition_id": market.condition_id,
            "question": market.question,
            "outcome": market.outcome_of(token_id),
            "event_slug": market.event_slug,
            "fee_rate": market.fee.rate,
            "neg_risk": market.neg_risk,
            "end_time": market.end_time,
            **extra,
        }

    async def execute(self, order: OrderRequest) -> Fill:
        if order.side is Side.BUY:
            return await self.buy(order)
        return await self.sell(order)

    async def buy(self, order: OrderRequest) -> Fill:
        token = order.instrument_id
        market = await self._market(token, max_age=None)
        if market.resolved or not market.tradable:
            raise ExecutionRefused(f"market {market.market_id} is not open for orders")
        book = await self._book(token)
        if book.best_ask is None:
            raise ExecutionRefused("no asks on the book")
        limit = order.limit_price
        if limit is None:
            limit = book.best_ask + self.settings.max_slippage
        limit = min(limit, self.settings.price_cap)
        if book.best_ask > limit + 1e-12:
            raise ExecutionRefused(
                f"best ask {book.best_ask:.3f} is above the limit {limit:.3f}"
            )
        notional = order.notional
        if notional is None:  # a size-based buy: spend what that many shares cost
            notional = float(order.size or 0.0) * limit
        walk = book.walk_buy(notional, limit=limit)
        size = floor_to(walk.size, self.settings.share_decimals)
        if order.size is not None:
            size = min(size, floor_to(order.size, self.settings.share_decimals))
        walk = trim_walk(walk, size)
        minimum = max(market.min_order_size, book.min_order_size)
        if walk.size <= 0 or walk.size + 1e-9 < minimum:
            raise ExecutionRefused(
                f"fill of {walk.size:.2f} shares is below the minimum {minimum:g}"
            )
        if walk.notional + 1e-9 < self.settings.min_notional:
            raise ExecutionRefused(
                f"fill of ${walk.notional:.2f} is below ${self.settings.min_notional:g}"
            )
        fee = walk_fee(walk, market.fee)
        return Fill(
            instrument_id=token,
            side=Side.BUY,
            size=walk.size,
            price=walk.notional / walk.size,
            notional=walk.notional,
            costs=TradeCosts({"fee": fee}, source=COST_SOURCE_MODELLED),
            reference=_reference("buy"),
            timestamp=self.clock(),
            simulated=True,
            metadata=self._metadata(
                market,
                token,
                best_ask=book.best_ask,
                limit=limit,
                levels=walk.levels,
                requested_notional=notional,
            ),
        )

    async def sell(self, order: OrderRequest) -> Fill:
        token = order.instrument_id
        size = floor_to(float(order.size or 0.0), self.settings.share_decimals)
        if size <= 0:
            raise ExecutionRefused("sell size rounds to zero shares")
        market = await self._market(token, max_age=0.0)
        payout = market.payout(token)
        if payout is not None:
            return Fill(
                instrument_id=token,
                side=Side.SELL,
                size=size,
                price=payout,
                notional=size * payout,
                costs=TradeCosts({"fee": 0.0}, source=COST_SOURCE_MODELLED),
                reference=_reference("redeem"),
                timestamp=self.clock(),
                simulated=True,
                metadata=self._metadata(market, token, redeemed=True),
            )
        if not market.tradable:
            raise ExecutionRefused(
                f"market {market.market_id} is closed and not yet resolved"
            )
        book = await self._book(token)
        if book.best_bid is None:
            raise ExecutionRefused("no bids on the book")
        limit = order.limit_price
        if limit is None:
            limit = max(0.0, book.best_bid - self.settings.max_slippage)
        walk = book.walk_sell(size, limit=limit)
        walk = trim_walk(walk, floor_to(walk.size, self.settings.share_decimals))
        if walk.size <= 0:
            raise ExecutionRefused(f"no bids at or above {limit:.3f}")
        fee = walk_fee(walk, market.fee)
        return Fill(
            instrument_id=token,
            side=Side.SELL,
            size=walk.size,
            price=walk.notional / walk.size,
            notional=walk.notional,
            costs=TradeCosts({"fee": fee}, source=COST_SOURCE_MODELLED),
            reference=_reference("sell"),
            timestamp=self.clock(),
            simulated=True,
            metadata=self._metadata(
                market,
                token,
                best_bid=book.best_bid,
                limit=limit,
                levels=walk.levels,
                partial=walk.size + 1e-9 < size,
            ),
        )


class LiveExecutor:
    """Placeholder for CLOB V2 order placement: refuses every order."""

    MESSAGE = (
        "live Polymarket execution is not implemented yet: it needs "
        "py-clob-client-v2, a funded pUSD proxy wallet and the stage-2 gate "
        "(docs/LIVE-TRADING.md)"
    )

    async def execute(self, order: OrderRequest) -> Fill:
        raise ExecutionRefused(self.MESSAGE)


__all__ = [
    "LiveExecutor",
    "PaperExecutor",
    "REASON_RESOLVED",
    "floor_to",
    "trim_walk",
    "walk_fee",
]
