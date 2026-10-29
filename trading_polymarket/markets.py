"""Polymarket markets as the module sees them (parsed from the Gamma API).

A *market* is one binary question (``conditionId``) with two outcome tokens
(``clobTokenIds``, usually ``["Yes", "No"]``). The engine trades **tokens**:
an instrument id is a token id, and buying the ``No`` token is how the module
takes the other side (there is no shorting).

Gamma encodes ``outcomes``, ``outcomePrices`` and ``clobTokenIds`` as JSON
strings; :meth:`Market.from_gamma` decodes them and refuses markets it cannot
trade (no tokens, mismatched lengths).

Resolution: a closed market whose ``outcomePrices`` are exactly ``1`` and ``0``
has resolved; the winning token pays 1 per share, the other 0.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from trading_polymarket.fees import FeeSchedule


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except ValueError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _float(value: Any, default: float | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_time(value: Any) -> float | None:
    """Epoch seconds from Gamma's ISO times (``Z``, ``+00``, date only)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    if text.endswith("+00"):
        text += ":00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


@dataclass(frozen=True)
class Market:
    market_id: str
    condition_id: str
    question: str
    token_ids: tuple[str, ...]
    outcomes: tuple[str, ...]
    outcome_prices: tuple[float, ...] = ()
    slug: str = ""
    event_id: str = ""
    event_slug: str = ""
    event_title: str = ""
    group_item_title: str = ""
    description: str = ""
    best_bid: float | None = None
    best_ask: float | None = None
    last_trade_price: float | None = None
    volume_24h: float = 0.0
    volume: float = 0.0
    liquidity: float = 0.0
    one_hour_change: float = 0.0
    one_day_change: float = 0.0
    end_time: float | None = None
    closed: bool = False
    active: bool = True
    accepting_orders: bool = True
    neg_risk: bool = False
    neg_risk_market_id: str = ""
    tick_size: float = 0.01
    min_order_size: float = 5.0
    fee: FeeSchedule = field(default_factory=FeeSchedule)
    fee_type: str = ""
    tags: tuple[str, ...] = ()

    @classmethod
    def from_gamma(
        cls,
        data: Mapping[str, Any],
        *,
        event: Mapping[str, Any] | None = None,
        default_fee_rate: float = 0.0,
    ) -> Market:
        tokens = tuple(str(t) for t in _json_list(data.get("clobTokenIds")))
        outcomes = tuple(str(o) for o in _json_list(data.get("outcomes")))
        if len(tokens) < 2 or len(tokens) != len(outcomes):
            raise ValueError(f"market {data.get('id')!r} has no tradable tokens")
        prices = tuple(
            p
            for p in (_float(x) for x in _json_list(data.get("outcomePrices")))
            if p is not None
        )
        events = data.get("events")
        if event is None and isinstance(events, list) and events:
            first = events[0]
            event = first if isinstance(first, Mapping) else None
        event = event or {}
        tags = tuple(
            str(t.get("slug") or t.get("label"))
            for t in (event.get("tags") or [])
            if isinstance(t, Mapping) and (t.get("slug") or t.get("label"))
        )
        return cls(
            market_id=str(data.get("id") or ""),
            condition_id=str(data.get("conditionId") or ""),
            question=str(data.get("question") or ""),
            token_ids=tokens,
            outcomes=outcomes,
            outcome_prices=prices if len(prices) == len(tokens) else (),
            slug=str(data.get("slug") or ""),
            event_id=str(event.get("id") or ""),
            event_slug=str(event.get("slug") or ""),
            event_title=str(event.get("title") or ""),
            group_item_title=str(data.get("groupItemTitle") or ""),
            description=str(data.get("description") or event.get("description") or ""),
            best_bid=_float(data.get("bestBid")),
            best_ask=_float(data.get("bestAsk")),
            last_trade_price=_float(data.get("lastTradePrice")),
            volume_24h=_float(data.get("volume24hr"), 0.0) or 0.0,
            volume=_float(data.get("volumeNum") or data.get("volume"), 0.0) or 0.0,
            liquidity=_float(data.get("liquidityNum") or data.get("liquidity"), 0.0)
            or 0.0,
            one_hour_change=_float(data.get("oneHourPriceChange"), 0.0) or 0.0,
            one_day_change=_float(data.get("oneDayPriceChange"), 0.0) or 0.0,
            end_time=parse_time(data.get("endDate") or event.get("endDate")),
            closed=bool(data.get("closed", False)),
            active=bool(data.get("active", True)),
            accepting_orders=bool(data.get("acceptingOrders", True)),
            neg_risk=bool(data.get("negRisk", False)),
            neg_risk_market_id=str(data.get("negRiskMarketID") or ""),
            tick_size=_float(data.get("orderPriceMinTickSize"), 0.01) or 0.01,
            min_order_size=_float(data.get("orderMinSize"), 5.0) or 5.0,
            fee=FeeSchedule.from_gamma(
                data.get("feeSchedule"),
                # No schedule on a market that charges fees: assume the worst
                # known rate so paper is never cheaper than live.
                default_rate=default_fee_rate if data.get("feesEnabled") else 0.0,
            ),
            fee_type=str(data.get("feeType") or ""),
            tags=tags,
        )

    # -- tokens ---------------------------------------------------------------
    def token_index(self, token_id: str) -> int:
        try:
            return self.token_ids.index(token_id)
        except ValueError as exc:
            raise KeyError(
                f"token {token_id} is not in market {self.market_id}"
            ) from exc

    def outcome_of(self, token_id: str) -> str:
        return self.outcomes[self.token_index(token_id)]

    def complement(self, token_id: str) -> str:
        """The other token of a binary market."""
        index = self.token_index(token_id)
        if len(self.token_ids) != 2:
            raise ValueError("complement is defined for binary markets only")
        return self.token_ids[1 - index]

    @property
    def yes_token(self) -> str:
        return self.token_ids[0]

    @property
    def no_token(self) -> str:
        return self.token_ids[1]

    # -- state ----------------------------------------------------------------
    @property
    def resolved(self) -> bool:
        """Closed with prices exactly 1 and 0: the winner is known."""
        if not self.closed or not self.outcome_prices:
            return False
        return sorted(self.outcome_prices) == [0.0] * (len(self.outcome_prices) - 1) + [
            1.0
        ]

    def payout(self, token_id: str) -> float | None:
        """1.0 for the winning token, 0.0 for a loser, ``None`` before resolution."""
        if not self.resolved:
            return None
        return self.outcome_prices[self.token_index(token_id)]

    def price_of(self, token_id: str) -> float | None:
        """Gamma's last price for this token (``outcomePrices``), if known.

        Each token has its own price; ``lastTradePrice`` is the *first*
        token's, so it must never stand in for the second one (TP-5).
        """
        if not self.outcome_prices:
            return None
        return self.outcome_prices[self.token_index(token_id)]

    @property
    def tradable(self) -> bool:
        return self.active and not self.closed and self.accepting_orders

    def hours_to_close(self, now: float) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - now) / 3600.0

    def label(self, token_id: str) -> str:
        """``Will X happen? · Yes`` shortened for tables."""
        title = self.group_item_title or self.question
        return f"{title[:40]} · {self.outcome_of(token_id)}"


def markets_from_event(
    event: Mapping[str, Any], *, default_fee_rate: float = 0.0
) -> list[Market]:
    """Every tradable market of a Gamma event (malformed ones are skipped)."""
    found: list[Market] = []
    for raw in event.get("markets") or []:
        if not isinstance(raw, Mapping):
            continue
        try:
            found.append(
                Market.from_gamma(raw, event=event, default_fee_rate=default_fee_rate)
            )
        except ValueError:
            continue
    return found


def index_by_token(markets: Iterable[Market]) -> dict[str, Market]:
    return {token: market for market in markets for token in market.token_ids}


__all__ = ["Market", "index_by_token", "markets_from_event", "parse_time"]
