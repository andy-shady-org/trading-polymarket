"""Screens every lane's candidates pass before an analyst sees them.

Thresholds are per lane (``module_settings.<lane>``): a weather bucket with
$300 of liquidity is normal, a politics market with that little is not.
Every filter records what it measured, so the numbers land in the buy's
``entry_metrics`` and ``trading-core-audit cuts`` can later test them.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from trading_core.strategy.pipeline import Candidate, Filter, Screening

from trading_polymarket.catalogue import BookCache
from trading_polymarket.clients.clob import BookUnavailable
from trading_polymarket.config import PolymarketSettings
from trading_polymarket.markets import Market
from trading_polymarket.strategies.common import KEY_LANE, KEY_MARKET


def _market(candidate: Candidate) -> Market:
    market = candidate.data.get(KEY_MARKET)
    if not isinstance(market, Market):
        raise ValueError("candidate carries no market")
    return market


class MarketStateFilter(Filter):
    """Open, accepting orders, unresolved, and busy enough for the lane."""

    name = "market-state"

    def __init__(
        self, settings: PolymarketSettings, *, clock: Callable[[], float] = time.time
    ) -> None:
        self.settings = settings
        self.clock = clock

    async def screen(self, candidate: Candidate) -> Screening:
        market = _market(candidate)
        lane = self.settings.lane(str(candidate.data.get(KEY_LANE)))
        hours = market.hours_to_close(self.clock())
        metrics = {
            "volume_24h": round(market.volume_24h, 2),
            "liquidity": round(market.liquidity, 2),
            "hours_to_close": None if hours is None else round(hours, 2),
            "fee_rate": market.fee.rate,
        }
        if not market.tradable or market.resolved:
            return Screening.reject("market not open for orders", **metrics)
        if market.volume_24h < lane.min_volume_24h:
            return Screening.reject(
                f"24h volume {market.volume_24h:,.0f} < {lane.min_volume_24h:,.0f}",
                **metrics,
            )
        if market.liquidity < lane.min_liquidity:
            return Screening.reject(
                f"liquidity {market.liquidity:,.0f} < {lane.min_liquidity:,.0f}",
                **metrics,
            )
        return Screening.accept(**metrics)


class BookFilter(Filter):
    """Reads the live book: spread and depth near the best ask."""

    name = "order-book"

    def __init__(self, settings: PolymarketSettings, books: BookCache) -> None:
        self.settings = settings
        self.books = books

    async def screen(self, candidate: Candidate) -> Screening:
        lane = self.settings.lane(str(candidate.data.get(KEY_LANE)))
        try:
            book = await self.books.get(candidate.instrument_id)
        except BookUnavailable as exc:
            return Screening.reject(str(exc))
        if book.best_ask is None or book.best_bid is None:
            return Screening.reject("one-sided book", best_ask=book.best_ask)
        spread = float(book.spread or 0.0)
        depth = book.depth("ask", within=lane.depth_window)
        metrics = {
            "best_bid": book.best_bid,
            "best_ask": book.best_ask,
            "spread": round(spread, 4),
            "ask_depth": round(depth, 2),
            "imbalance": round(book.imbalance(within=lane.depth_window), 3),
        }
        if spread > lane.max_spread + 1e-9:
            return Screening.reject(
                f"spread {spread:.3f} > {lane.max_spread:.3f}", **metrics
            )
        if depth < lane.min_ask_depth:
            return Screening.reject(
                f"ask depth ${depth:,.2f} < ${lane.min_ask_depth:,.2f}", **metrics
            )
        return Screening.accept(**metrics)


__all__ = ["BookFilter", "MarketStateFilter"]
