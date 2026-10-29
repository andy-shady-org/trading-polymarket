"""The favourite lane: the favourite-longshot bias near resolution.

Across prediction markets, contracts priced as heavy favourites tend to win a
little more often than their price implies, and longshots less often
(Snowberg & Wolfers 2010; Whelan 2024 on Betfair; the 2025 Kalshi/Polymarket
studies collected in ``runtime/polymarket/prediction-market-analysis``). The
lane buys favourites that close soon **only where a calibration table built
from real resolved Polymarket markets says the bias beats the price plus the
fee** (``trading-polymarket calibrate``). Without such a table it finds no
edge and trades nothing.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from trading_core.strategy.pipeline import Analyst, Candidate, Scout, Signal

from trading_polymarket.calibration import CalibrationTable
from trading_polymarket.catalogue import BookCache, MarketCatalogue
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.config import LANE_FAVOURITE, FavouriteLane
from trading_polymarket.markets import Market
from trading_polymarket.strategies.common import (
    KEY_FAIR,
    KEY_LANE,
    KEY_MARKET,
    net_edge,
    plan_buy,
    token_ask,
)


def iso(moment: float) -> str:
    return datetime.fromtimestamp(moment, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class FavouriteScout(Scout):
    """Binary markets closing inside the lane's window with a token in the band."""

    name = "closing-favourites"

    def __init__(
        self,
        gamma: GammaClient,
        catalogue: MarketCatalogue,
        calibration: CalibrationTable,
        lane: FavouriteLane,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.gamma = gamma
        self.catalogue = catalogue
        self.calibration = calibration
        self.lane = lane
        self.clock = clock

    def _excluded(self, market: Market) -> bool:
        return bool(set(market.tags) & set(self.lane.exclude_tags))

    def _score(
        self, market: Market, token: str, hours: float
    ) -> tuple[float, Candidate] | None:
        """``(net edge, candidate)`` for a calibrated favourite, else ``None``."""
        ask = token_ask(market, token)
        if ask is None or not self.lane.min_price <= ask <= self.lane.max_price:
            return None
        samples = self.calibration.samples(ask, hours)
        if samples < self.lane.min_samples:
            return None
        fair = self.calibration.win_rate(ask, hours)
        gap = net_edge(fair, ask, market.fee)
        if gap < self.lane.min_edge:
            return None
        return (
            gap,
            Candidate(
                instrument_id=token,
                name=market.label(token),
                source=self.name,
                data={
                    KEY_LANE: LANE_FAVOURITE,
                    KEY_MARKET: market,
                    KEY_FAIR: fair,
                    "calibration_n": samples,
                    "gamma_ask": ask,
                },
            ),
        )

    async def discover(self) -> Sequence[Candidate]:
        now = self.clock()
        markets = await self.gamma.markets(
            max_pages=self.lane.max_pages,
            closed=False,
            end_date_min=iso(now + self.lane.min_hours * 3600),
            end_date_max=iso(now + self.lane.max_hours * 3600),
            order="volume24hr",
            ascending=False,
        )
        self.catalogue.put(markets)
        scored: list[tuple[float, Candidate]] = []
        for market in markets:
            if len(market.token_ids) != 2 or self._excluded(market):
                continue
            hours = market.hours_to_close(now)
            if hours is None:
                continue
            for token in market.token_ids:
                found = self._score(market, token, hours)
                if found is not None:
                    scored.append(found)
        scored.sort(key=lambda item: item[0], reverse=True)
        return [c for _, c in scored[: self.lane.max_candidates]]


class FavouriteAnalyst(Analyst):
    """Re-reads the calibrated win rate at the live ask and sizes the buy."""

    name = "favourite-calibrated"

    def __init__(
        self,
        books: BookCache,
        calibration: CalibrationTable,
        lane: FavouriteLane,
        *,
        bankroll: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.books = books
        self.calibration = calibration
        self.lane = lane
        self.bankroll = bankroll
        self.clock = clock

    async def evaluate(
        self, candidate: Candidate, screening_metrics: Mapping[str, Any]
    ) -> Signal | None:
        market: Market = candidate.data[KEY_MARKET]
        hours = market.hours_to_close(self.clock()) or 0.0
        book = await self.books.get(candidate.instrument_id)
        if book.best_ask is None:
            return None
        if self.calibration.samples(book.best_ask, hours) < self.lane.min_samples:
            return None
        fair = self.calibration.win_rate(book.best_ask, hours)
        plan = plan_buy(
            book,
            fair,
            market.fee,
            self.lane,
            bankroll=self.bankroll,
            max_price=self.lane.max_price,
        )
        if plan is None:
            return None
        return Signal(
            instrument_id=candidate.instrument_id,
            reason=f"favourite calibrated {fair:.3f} vs {plan.average_price:.3f}",
            name=candidate.name,
            notional=plan.notional,
            limit_price=plan.limit,
            confidence=min(1.0, max(0.0, plan.edge * 10)),
            edge=plan.edge,
            strategy=LANE_FAVOURITE,
            metrics={
                KEY_FAIR: round(fair, 4),
                "calibration_n": self.calibration.samples(book.best_ask, hours),
                "hours_to_close": round(hours, 2),
                **plan.metrics(),
            },
        )


__all__ = ["FavouriteAnalyst", "FavouriteScout", "iso"]
