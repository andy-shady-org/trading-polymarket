"""Pricing helpers every lane shares: edge after fees, Kelly size, buy plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trading_polymarket.book import OrderBook
from trading_polymarket.config import LaneLimits
from trading_polymarket.fees import FeeSchedule

KEY_LANE = "lane"
KEY_MARKET = "market"
KEY_FAIR = "fair"


def net_edge(probability: float, price: float, fee: FeeSchedule) -> float:
    """Expected profit per share held to resolution: ``p - price - fee``."""
    return probability - price - fee.per_share(price)


def kelly_fraction(probability: float, cost: float) -> float:
    """Full-Kelly bankroll share for a binary paying 1 that costs ``cost``."""
    if cost >= 1.0 or probability <= cost:
        return 0.0
    return (probability - cost) / (1.0 - cost)


@dataclass(frozen=True)
class BuyPlan:
    limit: float
    notional: float
    average_price: float
    edge: float  # per share, after fees, at the average price
    available: float  # notional the book offers within the limit
    kelly: float

    def metrics(self) -> dict[str, Any]:
        return {
            "limit": round(self.limit, 4),
            "plan_notional": round(self.notional, 2),
            "avg_price": round(self.average_price, 4),
            "edge": round(self.edge, 4),
            "available": round(self.available, 2),
            "kelly": round(self.kelly, 4),
        }


def plan_buy(
    book: OrderBook,
    probability: float,
    fee: FeeSchedule,
    lane: LaneLimits,
    *,
    bankroll: float,
    max_price: float = 0.99,
) -> BuyPlan | None:
    """The largest buy that keeps ``lane.min_edge`` on every share, or ``None``.

    Walks the asks while each level's own edge (after its fee) stays at or above
    the lane's minimum, sizes with fractional Kelly on the average cost, caps at
    ``max_notional`` and what the book offers, and refuses below ``min_notional``.
    """
    eligible = []
    for level in book.asks:  # best first; the edge only falls as price rises
        if level.price > max_price or net_edge(probability, level.price, fee) < (
            lane.min_edge
        ):
            break
        eligible.append(level)
    if not eligible:
        return None
    limit = eligible[-1].price
    available = sum(level.price * level.size for level in eligible)
    best_cost = eligible[0].price + fee.per_share(eligible[0].price)
    kelly = kelly_fraction(probability, best_cost)
    notional = min(lane.kelly_fraction * kelly * bankroll, lane.max_notional, available)
    if notional + 1e-9 < lane.min_notional:
        return None
    walk = book.walk_buy(notional, limit=limit)
    average = walk.average_price or limit
    edge = probability - average - fee.per_share(average)
    return BuyPlan(limit, walk.notional, average, edge, available, kelly)


def token_ask(market: Any, token_id: str) -> float | None:
    """Gamma's best ask for a token (the No token's ask is ``1 - bestBid``)."""
    if token_id == market.token_ids[0]:
        return market.best_ask
    if market.best_bid is None:
        return None
    return round(1.0 - market.best_bid, 6)


def token_mid(market: Any, token_id: str) -> float | None:
    """Gamma's mid for a token (the No token's mid is ``1 - mid``)."""
    if market.best_bid is None or market.best_ask is None:
        return None
    mid = (market.best_bid + market.best_ask) / 2.0
    return mid if token_id == market.token_ids[0] else round(1.0 - mid, 6)


__all__ = [
    "BuyPlan",
    "KEY_FAIR",
    "KEY_LANE",
    "KEY_MARKET",
    "kelly_fraction",
    "net_edge",
    "plan_buy",
    "token_ask",
    "token_mid",
]
