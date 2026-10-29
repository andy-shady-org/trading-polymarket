"""Kalshi's free, keyless market-data API: a second opinion on the same events.

Kalshi (a CFTC-regulated exchange) lists many of the questions Polymarket
lists - Fed decisions, economic prints, elections, weather, sports. Its
public REST endpoints need no account for **reading**:

* ``GET /events?series_ticker=&status=&with_nested_markets=true`` (cursor paging);
* ``GET /events/{event_ticker}?with_nested_markets=true``;
* ``GET /markets/{ticker}`` and ``GET /markets/{ticker}/orderbook``;
* ``GET /series/{series}/markets/{ticker}/candlesticks`` (``start_ts``,
  ``end_ts``, ``period_interval=60``) - hourly bid/ask history;
* ``GET /historical/markets?event_ticker=`` and
  ``GET /historical/markets/{ticker}/candlesticks`` - the same for markets
  Kalshi has archived (settled events older than a few weeks list no
  nested markets and 404 on the series candlesticks).

Prices are dollars as strings (``"0.2000"``). A Kalshi book lists **bids**
on both sides: a Yes ask is ``1 - best No bid``. trading-polymarket never
trades on Kalshi; it reads Kalshi as a reference price for the ``fed`` and
``crossvenue`` lanes (docs/STRATEGIES.md).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from trading_polymarket.clients.http import JsonHttp, build_url
from trading_polymarket.markets import parse_time

KALSHI_URL = "https://api.elections.kalshi.com/trade-api/v2"
STATUS_OPEN = "open"
STATUS_SETTLED = "settled"


def dollars(value: Any) -> float | None:
    """A Kalshi ``*_dollars`` / ``*_fp`` string as a float (``None`` if absent)."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class KalshiMarket:
    ticker: str
    event_ticker: str
    title: str
    yes_label: str
    yes_bid: float | None
    yes_ask: float | None
    last: float | None
    volume_24h: float
    open_interest: float
    close_time: float | None
    status: str
    result: str = ""

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> KalshiMarket:
        def number(*keys: str) -> float | None:
            for key in keys:
                value = dollars(data.get(key))
                if value is not None:
                    return value
            return None

        yes_bid = number("yes_bid_dollars")
        yes_ask = number("yes_ask_dollars")
        return cls(
            ticker=str(data.get("ticker") or ""),
            event_ticker=str(data.get("event_ticker") or ""),
            title=str(data.get("title") or ""),
            yes_label=str(data.get("yes_sub_title") or data.get("subtitle") or ""),
            # A side with no orders reads 0 bid / 1 ask: treat as missing.
            yes_bid=yes_bid if yes_bid else None,
            yes_ask=yes_ask if yes_ask is not None and yes_ask < 1.0 else None,
            last=number("last_price_dollars"),
            volume_24h=number("volume_24h_fp", "volume_24h") or 0.0,
            open_interest=number("open_interest_fp", "open_interest") or 0.0,
            close_time=parse_time(data.get("close_time")),
            status=str(data.get("status") or ""),
            result=str(data.get("result") or ""),
        )

    @property
    def mid(self) -> float | None:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return (self.yes_bid + self.yes_ask) / 2.0

    @property
    def spread(self) -> float | None:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return self.yes_ask - self.yes_bid

    @property
    def settled_yes(self) -> bool | None:
        """``True``/``False`` once settled, ``None`` before."""
        if self.result == "yes":
            return True
        if self.result == "no":
            return False
        return None


@dataclass(frozen=True)
class KalshiEvent:
    event_ticker: str
    series_ticker: str
    title: str
    markets: tuple[KalshiMarket, ...]

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> KalshiEvent:
        return cls(
            event_ticker=str(data.get("event_ticker") or ""),
            series_ticker=str(data.get("series_ticker") or ""),
            title=str(data.get("title") or ""),
            markets=tuple(
                KalshiMarket.from_api(m)
                for m in data.get("markets") or []
                if isinstance(m, Mapping)
            ),
        )


@dataclass(frozen=True)
class Candle:
    """One hour of a market: its last Yes bid and ask (dollars), contracts traded."""

    t: float
    yes_bid: float | None
    yes_ask: float | None
    volume: float = 0.0

    @property
    def mid(self) -> float | None:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return (self.yes_bid + self.yes_ask) / 2.0


def _close(side: Any) -> float | None:
    """A candle side's close: ``close_dollars`` (live) or ``close`` (archived)."""
    if not isinstance(side, Mapping):
        return None
    value = dollars(side.get("close_dollars"))
    return value if value is not None else dollars(side.get("close"))


def parse_candles(payload: Any) -> list[Candle]:
    rows = payload.get("candlesticks") if isinstance(payload, Mapping) else None
    out = []
    for row in rows or []:
        if not isinstance(row, Mapping) or row.get("end_period_ts") is None:
            continue
        bid = _close(row.get("yes_bid"))
        ask = _close(row.get("yes_ask"))
        volume = dollars(row.get("volume_fp"))
        out.append(
            Candle(
                t=float(row["end_period_ts"]),
                yes_bid=bid if bid else None,
                yes_ask=ask if ask is not None and ask < 1.0 else None,
                volume=(
                    volume if volume is not None else dollars(row.get("volume")) or 0.0
                ),
            )
        )
    out.sort(key=lambda c: c.t)
    return out


def candle_at(candles: Sequence[Candle], moment: float) -> Candle | None:
    """The last candle that ended at or before ``moment`` (no look-ahead)."""
    best = None
    for candle in candles:
        if candle.t > moment:
            break
        best = candle
    return best


class KalshiClient:
    def __init__(self, http: JsonHttp, *, base_url: str = KALSHI_URL) -> None:
        self.http = http
        self.base_url = base_url

    def _url(self, path: str, params: Mapping[str, Any] | None = None) -> str:
        return build_url(self.base_url, path, params)

    async def events(
        self,
        *,
        series_ticker: str | None = None,
        status: str | None = STATUS_OPEN,
        max_pages: int = 5,
        limit: int = 200,
    ) -> list[KalshiEvent]:
        found: list[KalshiEvent] = []
        cursor: str | None = None
        for _ in range(max(1, max_pages)):
            payload = await self.http.get_json(
                self._url(
                    "/events",
                    {
                        "series_ticker": series_ticker,
                        "status": status,
                        "with_nested_markets": True,
                        "limit": limit,
                        "cursor": cursor,
                    },
                )
            )
            rows = payload.get("events") if isinstance(payload, Mapping) else None
            found.extend(
                KalshiEvent.from_api(e) for e in rows or [] if isinstance(e, Mapping)
            )
            cursor = payload.get("cursor") if isinstance(payload, Mapping) else None
            if not cursor or not rows:
                break
        return found

    async def event(self, event_ticker: str) -> KalshiEvent:
        payload = await self.http.get_json(
            self._url(f"/events/{event_ticker}", {"with_nested_markets": True})
        )
        data = payload.get("event") if isinstance(payload, Mapping) else None
        return KalshiEvent.from_api(data or {})

    async def market(self, ticker: str) -> KalshiMarket:
        payload = await self.http.get_json(self._url(f"/markets/{ticker}"))
        data = payload.get("market") if isinstance(payload, Mapping) else None
        return KalshiMarket.from_api(data or {})

    async def historical_markets(self, event_ticker: str) -> list[KalshiMarket]:
        """An archived event's markets (with their ``result``)."""
        payload = await self.http.get_json(
            self._url("/historical/markets", {"event_ticker": event_ticker})
        )
        rows = payload.get("markets") if isinstance(payload, Mapping) else None
        return [KalshiMarket.from_api(m) for m in rows or [] if isinstance(m, Mapping)]

    async def candlesticks(
        self,
        series_ticker: str,
        ticker: str,
        *,
        start: float,
        end: float,
        period_minutes: int = 60,
        historical: bool = False,
    ) -> list[Candle]:
        path = (
            f"/historical/markets/{ticker}/candlesticks"
            if historical
            else f"/series/{series_ticker}/markets/{ticker}/candlesticks"
        )
        payload = await self.http.get_json(
            self._url(
                path,
                {
                    "start_ts": int(start),
                    "end_ts": int(end),
                    "period_interval": period_minutes,
                },
            )
        )
        return parse_candles(payload)


__all__ = [
    "KALSHI_URL",
    "STATUS_OPEN",
    "STATUS_SETTLED",
    "Candle",
    "KalshiClient",
    "KalshiEvent",
    "KalshiMarket",
    "candle_at",
    "dollars",
    "parse_candles",
]
