"""CLOB order books and the fills they would give.

The CLOB ``/book`` endpoint lists ``bids`` ascending and ``asks`` descending
(best price **last**); :meth:`OrderBook.from_clob` turns both into best-first
lists. A paper fill walks these levels exactly as a marketable order would:
it never fills at a better price than the book shows and never fills more than
the book holds (pumpfun "No Read, No Fill").
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

_EPS = 1e-12


@dataclass(frozen=True)
class Level:
    price: float
    size: float


@dataclass(frozen=True)
class Walk:
    """The outcome of walking one side of the book."""

    size: float
    notional: float
    parts: tuple[Level, ...] = ()

    @property
    def levels(self) -> int:
        return len(self.parts)

    @property
    def worst_price(self) -> float | None:
        return self.parts[-1].price if self.parts else None

    @property
    def average_price(self) -> float | None:
        return self.notional / self.size if self.size > _EPS else None


def _walk(parts: list[Level]) -> Walk:
    return Walk(
        size=sum(p.size for p in parts),
        notional=sum(p.size * p.price for p in parts),
        parts=tuple(parts),
    )


def _levels(raw: Any) -> list[Level]:
    out: list[Level] = []
    for item in raw or []:
        if not isinstance(item, Mapping):
            continue
        try:
            price, size = float(item["price"]), float(item["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if price > 0 and size > 0:
            out.append(Level(price, size))
    return out


@dataclass(frozen=True)
class OrderBook:
    token_id: str
    bids: tuple[Level, ...]  # best (highest) first
    asks: tuple[Level, ...]  # best (lowest) first
    timestamp: float | None = None
    tick_size: float = 0.01
    min_order_size: float = 0.0
    last_trade_price: float | None = None

    @classmethod
    def from_clob(cls, data: Mapping[str, Any]) -> OrderBook:
        bids = sorted(_levels(data.get("bids")), key=lambda lv: lv.price, reverse=True)
        asks = sorted(_levels(data.get("asks")), key=lambda lv: lv.price)
        timestamp = data.get("timestamp")
        try:
            ts = float(timestamp) / 1000.0 if timestamp is not None else None
        except (TypeError, ValueError):
            ts = None

        def num(key: str, default: float | None) -> float | None:
            try:
                return float(data[key])
            except (KeyError, TypeError, ValueError):
                return default

        return cls(
            token_id=str(data.get("asset_id") or ""),
            bids=tuple(bids),
            asks=tuple(asks),
            timestamp=ts,
            tick_size=num("tick_size", 0.01) or 0.01,
            min_order_size=num("min_order_size", 0.0) or 0.0,
            last_trade_price=num("last_trade_price", None),
        )

    @classmethod
    def from_levels(
        cls,
        token_id: str,
        bids: Iterable[tuple[float, float]],
        asks: Iterable[tuple[float, float]],
        **extra: Any,
    ) -> OrderBook:
        return cls(
            token_id=token_id,
            bids=tuple(
                sorted((Level(p, s) for p, s in bids), key=lambda lv: -lv.price)
            ),
            asks=tuple(sorted((Level(p, s) for p, s in asks), key=lambda lv: lv.price)),
            **extra,
        )

    # -- top of book -----------------------------------------------------------
    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    def depth(self, side: str, *, within: float) -> float:
        """Notional within ``within`` of the best price on ``side`` (bid/ask)."""
        levels = self.bids if side == "bid" else self.asks
        if not levels:
            return 0.0
        best = levels[0].price
        return float(
            sum(lv.price * lv.size for lv in levels if abs(lv.price - best) <= within)
        )

    def imbalance(self, *, within: float = 0.05) -> float:
        """(bid depth − ask depth) / total near the top, in [−1, 1]."""
        bid, ask = self.depth("bid", within=within), self.depth("ask", within=within)
        total = bid + ask
        return (bid - ask) / total if total > 0 else 0.0

    # -- fills -----------------------------------------------------------------
    def walk_buy(self, notional: float, *, limit: float | None = None) -> Walk:
        """Spend up to ``notional`` on asks priced at most ``limit``."""
        remaining = float(notional)
        parts: list[Level] = []
        for level in self.asks:
            if remaining <= _EPS or (limit is not None and level.price > limit + _EPS):
                break
            take = min(level.size, remaining / level.price)
            parts.append(Level(level.price, take))
            remaining -= take * level.price
        return _walk(parts)

    def walk_sell(self, size: float, *, limit: float | None = None) -> Walk:
        """Sell up to ``size`` into bids priced at least ``limit``."""
        remaining = float(size)
        parts: list[Level] = []
        for level in self.bids:
            if remaining <= _EPS or (limit is not None and level.price < limit - _EPS):
                break
            take = min(level.size, remaining)
            parts.append(Level(level.price, take))
            remaining -= take
        return _walk(parts)


__all__ = ["Level", "OrderBook", "Walk"]
