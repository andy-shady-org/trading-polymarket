"""The momentum lane (research): follow sharp moves on busy markets.

There is **no modelled edge** here. The lane exists to collect evidence: it
buys small, fixed amounts of the token that just moved up sharply and
records the move, the book and (optionally) news attention as entry metrics.
After the paper pilot, ``trading-core-audit cuts`` and
``verdict --strategy momentum`` decide whether any of it predicted anything.
It is off by default (docs/STRATEGIES.md, docs/GO-NO-GO.md).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from trading_core.strategy.pipeline import Analyst, Candidate, Scout, Signal

from trading_polymarket.catalogue import BookCache, MarketCatalogue
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.news import NewsClient
from trading_polymarket.config import LANE_MOMENTUM, MomentumLane
from trading_polymarket.markets import Market
from trading_polymarket.strategies.common import KEY_LANE, KEY_MARKET, token_ask


class MomentumScout(Scout):
    name = "sharp-moves"

    def __init__(
        self,
        gamma: GammaClient,
        catalogue: MarketCatalogue,
        lane: MomentumLane,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.gamma = gamma
        self.catalogue = catalogue
        self.lane = lane
        self.clock = clock

    async def discover(self) -> Sequence[Candidate]:
        now = self.clock()
        markets = await self.gamma.markets(
            max_pages=self.lane.max_pages,
            closed=False,
            order="volume24hr",
            ascending=False,
        )
        self.catalogue.put(markets)
        found: list[tuple[float, Candidate]] = []
        for market in markets:
            move = market.one_hour_change
            hours = market.hours_to_close(now)
            if len(market.token_ids) != 2 or abs(move) < self.lane.min_move:
                continue
            if hours is not None and hours < self.lane.min_hours:
                continue
            token = market.yes_token if move > 0 else market.no_token
            ask = token_ask(market, token)
            if ask is None or not self.lane.min_price <= ask <= self.lane.max_price:
                continue
            found.append(
                (
                    abs(move),
                    Candidate(
                        instrument_id=token,
                        name=market.label(token),
                        source=self.name,
                        data={
                            KEY_LANE: LANE_MOMENTUM,
                            KEY_MARKET: market,
                            "move_1h": round(move, 4),
                            "move_24h": round(market.one_day_change, 4),
                            "gamma_ask": ask,
                        },
                    ),
                )
            )
        found.sort(key=lambda item: item[0], reverse=True)
        return [c for _, c in found[: self.lane.max_candidates]]


class MomentumAnalyst(Analyst):
    name = "momentum-follow"

    def __init__(
        self,
        books: BookCache,
        lane: MomentumLane,
        *,
        news: NewsClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.books = books
        self.lane = lane
        self.news = news
        self.clock = clock

    async def _attention(self, market: Market) -> int | None:
        if self.news is None:
            return None
        try:
            return await self.news.attention(market.question[:120], now=self.clock())
        except Exception:  # attention is a metric, never a reason to skip
            return None

    async def evaluate(
        self, candidate: Candidate, screening_metrics: Mapping[str, Any]
    ) -> Signal | None:
        market: Market = candidate.data[KEY_MARKET]
        book = await self.books.get(candidate.instrument_id)
        if book.best_ask is None or book.best_ask > self.lane.max_price:
            return None
        limit = round(min(self.lane.max_price, book.best_ask + book.tick_size), 4)
        walk = book.walk_buy(self.lane.min_notional, limit=limit)
        if walk.notional + 1e-9 < self.lane.min_notional:
            return None
        metrics: dict[str, Any] = {
            key: value
            for key, value in candidate.data.items()
            if key not in (KEY_MARKET, KEY_LANE)
        }
        attention = await self._attention(market)
        if attention is not None:
            metrics["news_6h"] = attention
        return Signal(
            instrument_id=candidate.instrument_id,
            reason=f"momentum {candidate.data['move_1h']:+.2f} in 1h",
            name=candidate.name,
            notional=self.lane.min_notional,
            limit_price=limit,
            confidence=0.3,
            strategy=LANE_MOMENTUM,
            metrics=metrics,
        )


__all__ = ["MomentumAnalyst", "MomentumScout"]
