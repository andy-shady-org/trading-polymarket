"""Polymarket's data API: every trade printed in a market (free, keyless).

``GET /v2/trades?condition_id=<market>&limit=500`` lists a market's trades,
newest first, paged with a cursor (``pagination.has_more`` /
``pagination.next_cursor``). Each row is one taker order as it filled: the
taker's wallet, ``side`` (``BUY`` / ``SELL``), the outcome it traded
(``outcome_index``), its average ``price`` and ``size`` in shares, and a
``timestamp`` to the second. Makers do not appear, so the rows are the prints
a taker could have joined, not the book. The first version of this endpoint
(``/trades``) answers 410 since late October 2026.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from trading_polymarket.clients.http import JsonHttp, build_url

DATA_API_URL = "https://data-api.polymarket.com"
TRADES_PAGE = 500
# A 5-minute Up/Down market prints about 1,000 trades; this caps a runaway.
MAX_TRADE_PAGES = 200


@dataclass(frozen=True)
class TradePrint:
    """One taker order as it filled."""

    timestamp: float
    outcome_index: int
    side: str
    price: float
    size: float
    wallet: str = ""
    transaction_hash: str = ""

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> TradePrint | None:
        """A ``/v2/trades`` row, or ``None`` when it is malformed."""
        try:
            side = str(raw["side"]).upper()
            if side not in ("BUY", "SELL"):
                return None
            return cls(
                timestamp=float(raw["timestamp"]),
                outcome_index=int(raw["outcome_index"]),
                side=side,
                price=float(raw["price"]),
                size=float(raw["size"]),
                wallet=str(raw.get("proxy_wallet") or "").lower(),
                transaction_hash=str(raw.get("transaction_hash") or "").lower(),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _prints(rows: list[Any]) -> list[TradePrint]:
    parsed = (TradePrint.from_api(r) for r in rows if isinstance(r, Mapping))
    return [p for p in parsed if p is not None]


class DataApiClient:
    def __init__(self, http: JsonHttp, *, base_url: str = DATA_API_URL) -> None:
        self.http = http
        self.base_url = base_url

    async def trades(
        self, condition_id: str, *, max_pages: int = MAX_TRADE_PAGES
    ) -> list[TradePrint]:
        """Every trade in a market, oldest first (malformed rows skipped)."""
        found: list[TradePrint] = []
        cursor: str | None = None
        for _ in range(max(1, max_pages)):
            payload = await self.http.get_json(
                build_url(
                    self.base_url,
                    "/v2/trades",
                    {
                        "condition_id": condition_id,
                        "limit": TRADES_PAGE,
                        "cursor": cursor,
                    },
                )
            )
            if not isinstance(payload, Mapping):
                break
            rows = payload.get("data")
            rows = rows if isinstance(rows, list) else []
            found.extend(_prints(rows))
            page = payload.get("pagination")
            page = page if isinstance(page, Mapping) else {}
            cursor = page.get("next_cursor") or None
            if not rows or not cursor or not page.get("has_more"):
                break
        # Newest first from the API; a stable sort keeps same-second order.
        found.reverse()
        found.sort(key=lambda p: p.timestamp)
        return found


__all__ = ["DATA_API_URL", "MAX_TRADE_PAGES", "DataApiClient", "TradePrint"]
