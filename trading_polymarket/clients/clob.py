"""The CLOB API's free, keyless read endpoints.

* ``GET /book?token_id=`` - the order book of one outcome token. A token whose
  market closed answers 404; :class:`BookUnavailable` says so, so the module
  can look the market up and settle at resolution instead.
* ``GET /prices-history?market=<token>&startTs=&endTs=&fidelity=<minutes>`` -
  a price series ``{"history": [{"t": epoch, "p": price}, ...]}``, resolved
  markets included. Both ends of the window must be given (``endTs`` alone
  is a 400), and ``interval=max`` returns an *empty* series at hourly
  fidelity for long-lived markets, so research always asks for a window.

Published limits: ``/book`` 1500 / 10 s, ``/prices-history`` 1000 / 10 s.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from trading_polymarket.book import OrderBook
from trading_polymarket.clients.http import HttpError, JsonHttp, build_url

CLOB_URL = "https://clob.polymarket.com"


class BookUnavailable(RuntimeError):
    """No order book for this token (closed market, unknown token)."""


@dataclass(frozen=True)
class PricePoint:
    t: float
    p: float


def parse_history(payload: Any) -> list[PricePoint]:
    rows = payload.get("history") if isinstance(payload, Mapping) else payload
    points: list[PricePoint] = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        try:
            points.append(PricePoint(float(row["t"]), float(row["p"])))
        except (KeyError, TypeError, ValueError):
            continue
    points.sort(key=lambda point: point.t)
    return points


def price_at(points: list[PricePoint], moment: float) -> float | None:
    """The last price printed at or before ``moment`` (no look-ahead)."""
    best: float | None = None
    for point in points:
        if point.t > moment:
            break
        best = point.p
    return best


class ClobClient:
    def __init__(self, http: JsonHttp, *, base_url: str = CLOB_URL) -> None:
        self.http = http
        self.base_url = base_url

    async def book(self, token_id: str) -> OrderBook:
        url = build_url(self.base_url, "/book", {"token_id": token_id})
        try:
            payload = await self.http.get_json(url)
        except HttpError as exc:
            if exc.status in (400, 404):
                raise BookUnavailable(f"no order book for {token_id}") from exc
            raise
        if not isinstance(payload, Mapping):
            raise BookUnavailable(f"malformed order book for {token_id}")
        book = OrderBook.from_clob(payload)
        if not book.token_id:
            book = OrderBook(
                token_id=token_id,
                bids=book.bids,
                asks=book.asks,
                timestamp=book.timestamp,
                tick_size=book.tick_size,
                min_order_size=book.min_order_size,
                last_trade_price=book.last_trade_price,
            )
        return book

    async def prices_history(
        self,
        token_id: str,
        *,
        fidelity: int = 60,
        start: float | None = None,
        end: float | None = None,
    ) -> list[PricePoint]:
        """A token's price series, ``fidelity`` minutes apart.

        With ``start`` the request is an explicit ``startTs``/``endTs`` window
        (``end`` defaults to ``start`` + 7 days): ``interval=max`` returns an
        empty series at hourly fidelity for long-lived markets. Without it,
        ``interval=max``. Points outside the window are trimmed either way.
        """
        params: dict[str, Any] = {"market": token_id, "fidelity": fidelity}
        if start is None:
            params["interval"] = "max"
        else:
            params["startTs"] = int(start)
            params["endTs"] = int(end if end is not None else start + 7 * 86400)
        url = build_url(self.base_url, "/prices-history", params)
        points = parse_history(await self.http.get_json(url))
        return [
            p
            for p in points
            if (start is None or p.t >= start) and (end is None or p.t <= end)
        ]


__all__ = [
    "BookUnavailable",
    "CLOB_URL",
    "ClobClient",
    "PricePoint",
    "parse_history",
    "price_at",
]
