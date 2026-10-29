"""The ``fed`` and ``crossvenue`` lanes: Polymarket priced against Kalshi.

When the same question trades on both venues, the other venue's quote is a
fair-value estimate made by a different crowd with different fees, users and
market makers. The lanes buy a Polymarket token when its ask is below that
reference by more than ``min_edge`` after Polymarket's fee, and sell when the
gap has closed (``exit_on_convergence``) or hold to resolution.

* ``fed``: pairs come from :func:`~trading_polymarket.pairs.match_fed`
  (Polymarket "Fed Decision in <Month>?" vs Kalshi ``KXFEDDECISION``).
* ``crossvenue``: pairs come from the reviewed pairs file.

Guards: the Kalshi quote must be tight (``max_reference_spread``), traded
(``min_reference_volume``) and recent (``max_reference_age_seconds``); a gap
above ``max_edge`` is treated as a sign the two markets do not settle the same
way, not as money. Kalshi is only read, never traded.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from trading_core.strategy.pipeline import Analyst, Candidate, Scout, Signal

from trading_polymarket.catalogue import BookCache, MarketCatalogue
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.http import HttpError
from trading_polymarket.clients.kalshi import KalshiClient, KalshiEvent, KalshiMarket
from trading_polymarket.config import REFERENCE_BID, ReferenceLane
from trading_polymarket.markets import Market, markets_from_event
from trading_polymarket.pairs import (
    FED_SERIES,
    Reference,
    VenuePair,
    load_pairs,
    match_fed,
)
from trading_polymarket.strategies.common import (
    KEY_FAIR,
    KEY_LANE,
    KEY_MARKET,
    net_edge,
    plan_buy,
    token_ask,
)

KEY_PAIR = "pair"
Listing = tuple[VenuePair, Market, KalshiMarket]


def reference_fair(reference: Reference, lane: ReferenceLane) -> float | None:
    """The fair value a reference quote implies under the lane's setting."""
    return reference.bid if lane.reference == REFERENCE_BID else reference.mid


def usable(reference: Reference, lane: ReferenceLane, now: float) -> str | None:
    """Why ``reference`` cannot price a trade (``None``: it can)."""
    if reference.spread is None:
        return "no two-sided Kalshi quote"
    if reference.spread > lane.max_reference_spread + 1e-9:
        return f"Kalshi spread {reference.spread:.3f} too wide"
    if reference.volume_24h < lane.min_reference_volume:
        return f"Kalshi 24h volume {reference.volume_24h:,.0f} too thin"
    if now - reference.timestamp > lane.max_reference_age_seconds:
        return "Kalshi quote too old"
    return None


def converged(
    reference: Reference | None, bid: float | None, lane: ReferenceLane, now: float
) -> bool:
    """Has the Polymarket bid caught up with the reference? (exit signal)"""
    if reference is None or bid is None or not lane.exit_on_convergence:
        return False
    if now - reference.timestamp > lane.max_reference_age_seconds:
        return False
    fair = reference.mid
    return fair is not None and bid >= fair - lane.convergence_margin


class ReferenceBook:
    """Latest Kalshi references per Polymarket token, plus cached fetches."""

    def __init__(
        self,
        kalshi: KalshiClient,
        *,
        ttl: float = 60.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.kalshi = kalshi
        self.ttl = ttl
        self.clock = clock
        self._references: dict[str, Reference] = {}
        self._markets: dict[str, tuple[KalshiMarket, float]] = {}
        self._events: dict[str, tuple[list[KalshiEvent], float]] = {}

    def remember(self, token: str, reference: Reference) -> None:
        self._references[token] = reference

    def latest(self, token: str) -> Reference | None:
        return self._references.get(token)

    async def market(self, ticker: str) -> KalshiMarket:
        now = self.clock()
        cached = self._markets.get(ticker)
        if cached and now - cached[1] < self.ttl:
            return cached[0]
        market = await self.kalshi.market(ticker)
        self._markets[ticker] = (market, now)
        return market

    async def series_events(self, series: str) -> list[KalshiEvent]:
        now = self.clock()
        cached = self._events.get(series)
        if cached and now - cached[1] < self.ttl:
            return cached[0]
        events = await self.kalshi.events(series_ticker=series)
        self._events[series] = (events, now)
        return events


class PairSource(ABC):
    """Where a reference lane's pairs come from."""

    @abstractmethod
    async def listings(self) -> list[Listing]:
        """Every live pair with its Polymarket market and Kalshi market."""


class FedPairs(PairSource):
    """Polymarket Fed-decision events matched with Kalshi's, every cycle."""

    def __init__(
        self,
        gamma: GammaClient,
        catalogue: MarketCatalogue,
        references: ReferenceBook,
        *,
        query: str = "Fed Decision in",
    ) -> None:
        self.gamma = gamma
        self.catalogue = catalogue
        self.references = references
        self.query = query

    async def listings(self) -> list[Listing]:
        raw = await self.gamma.search_events(self.query, status="active")
        pm_events = [
            (
                event,
                markets_from_event(event, default_fee_rate=self.gamma.default_fee_rate),
            )
            for event in raw
        ]
        for _, markets in pm_events:
            self.catalogue.put(markets)
        kalshi_events = await self.references.series_events(FED_SERIES)
        by_ticker = {m.ticker: m for e in kalshi_events for m in e.markets}
        by_token = {t: m for _, ms in pm_events for m in ms for t in m.token_ids}
        return [
            (pair, by_token[pair.pm_token], by_ticker[pair.kalshi_ticker])
            for pair in match_fed(pm_events, kalshi_events)
        ]


class ApprovedPairs(PairSource):
    """Pairs a human reviewed (``data/pairs.json``), reloaded when it changes."""

    def __init__(
        self,
        path: str,
        catalogue: MarketCatalogue,
        references: ReferenceBook,
    ) -> None:
        self.path = path
        self.catalogue = catalogue
        self.references = references
        self._pairs: list[VenuePair] = []
        self._mtime: float | None = None

    def pairs(self) -> list[VenuePair]:
        target = Path(self.path)
        mtime = target.stat().st_mtime if target.is_file() else None
        if mtime != self._mtime:
            self._pairs = load_pairs(target)
            self._mtime = mtime
        return self._pairs

    async def listings(self) -> list[Listing]:
        pairs = self.pairs()
        if not pairs:
            return []
        # One batched Gamma lookup per cycle keeps every pair's ask fresh.
        await self.catalogue.refresh(p.pm_token for p in pairs)
        found: list[Listing] = []
        for pair in pairs:
            market = self.catalogue.cached(pair.pm_token)
            if market is None:
                continue
            try:
                kalshi = await self.references.market(pair.kalshi_ticker)
            except HttpError:
                continue  # one unreadable Kalshi market must not stop the rest
            found.append((pair, market, kalshi))
        return found


class ReferenceScout(Scout):
    """Polymarket tokens whose ask sits below the Kalshi reference."""

    def __init__(
        self,
        name: str,
        lane_name: str,
        source: PairSource,
        references: ReferenceBook,
        lane: ReferenceLane,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.name = name
        self.lane_name = lane_name
        self.source = source
        self.references = references
        self.lane = lane
        self.clock = clock
        self.last_pairs = 0

    async def discover(self) -> Sequence[Candidate]:
        now = self.clock()
        listings = await self.source.listings()
        self.last_pairs = len(listings)
        scored: list[tuple[float, Candidate]] = []
        for pair, market, kalshi in listings:
            reference = Reference.of(kalshi, pair.kalshi_side, now)
            # Every listed token's reference is kept, held ones included, so
            # the convergence exit always sees a fresh quote.
            self.references.remember(pair.pm_token, reference)
            hours = market.hours_to_close(now)
            if not market.tradable or (
                hours is not None and hours < self.lane.min_hours
            ):
                continue
            if usable(reference, self.lane, now) is not None:
                continue
            fair = reference_fair(reference, self.lane)
            ask = token_ask(market, pair.pm_token)
            if fair is None or ask is None:
                continue
            if not self.lane.min_price <= ask <= self.lane.max_price:
                continue
            gap = net_edge(fair, ask, market.fee)
            if not self.lane.min_edge / 2 <= gap <= self.lane.max_edge:
                continue
            scored.append(
                (
                    gap,
                    Candidate(
                        instrument_id=pair.pm_token,
                        name=pair.label or market.label(pair.pm_token),
                        source=self.name,
                        data={
                            KEY_LANE: self.lane_name,
                            KEY_MARKET: market,
                            KEY_PAIR: pair,
                            "kalshi_ticker": pair.kalshi_ticker,
                            "kalshi_side": pair.kalshi_side,
                            "gamma_ask": ask,
                        },
                    ),
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [c for _, c in scored[: self.lane.max_candidates]]


class ReferenceAnalyst(Analyst):
    """Re-prices against the freshest reference and the live Polymarket book."""

    def __init__(
        self,
        name: str,
        lane_name: str,
        books: BookCache,
        references: ReferenceBook,
        lane: ReferenceLane,
        *,
        bankroll: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.name = name
        self.lane_name = lane_name
        self.books = books
        self.references = references
        self.lane = lane
        self.bankroll = bankroll
        self.clock = clock

    async def evaluate(
        self, candidate: Candidate, screening_metrics: Mapping[str, Any]
    ) -> Signal | None:
        market: Market = candidate.data[KEY_MARKET]
        reference = self.references.latest(candidate.instrument_id)
        if reference is None or usable(reference, self.lane, self.clock()) is not None:
            return None
        fair = reference_fair(reference, self.lane)
        book = await self.books.get(candidate.instrument_id)
        ask = book.best_ask
        if fair is None or ask is None:
            return None
        if not self.lane.min_price <= ask <= self.lane.max_price:
            return None
        if net_edge(fair, ask, market.fee) > self.lane.max_edge:
            return None
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
        metrics: dict[str, Any] = {
            "kalshi_ticker": candidate.data["kalshi_ticker"],
            "kalshi_side": candidate.data["kalshi_side"],
            "kalshi_bid": reference.bid,
            "kalshi_ask": reference.ask,
            "kalshi_spread": round(reference.spread or 0.0, 4),
            "kalshi_volume_24h": round(reference.volume_24h, 1),
            "gamma_ask": candidate.data["gamma_ask"],
            KEY_FAIR: round(fair, 4),
            **plan.metrics(),
        }
        return Signal(
            instrument_id=candidate.instrument_id,
            reason=f"{self.lane_name}: Kalshi {fair:.3f} vs {plan.average_price:.3f}",
            name=candidate.name,
            notional=plan.notional,
            limit_price=plan.limit,
            confidence=min(1.0, max(0.0, plan.edge * 10)),
            edge=plan.edge,
            strategy=self.lane_name,
            metrics=metrics,
        )


__all__ = [
    "ApprovedPairs",
    "FedPairs",
    "KEY_PAIR",
    "PairSource",
    "ReferenceAnalyst",
    "ReferenceBook",
    "ReferenceScout",
    "converged",
    "reference_fair",
    "usable",
]
