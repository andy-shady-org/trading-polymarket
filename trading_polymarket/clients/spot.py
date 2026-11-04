"""Spot prices a second apart: Binance's public market-data mirror.

``GET https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1s``
returns up to 1,000 one-second candles from ``startTime`` (milliseconds).
It is Binance's keyless mirror for public market data and answers from
places ``api.binance.com`` refuses (HTTP 451 for a restricted location).
A second with no trade has no candle, so a day may hold fewer than 86,400.

Crypto Up/Down markets settle on Chainlink's 60-second average, not on
Binance; Gamma gives the exact start and end prices of a settled market
(``priceToBeat``, ``finalPrice``), and these closes are the path between.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from trading_polymarket.clients.http import JsonHttp, build_url

SPOT_URL = "https://data-api.binance.vision"
KLINES_LIMIT = 1000


def parse_klines(payload: Any) -> list[tuple[float, float]]:
    """``(open time in seconds, close)`` for each well-formed candle."""
    found: list[tuple[float, float]] = []
    for row in payload if isinstance(payload, list) else []:
        if not isinstance(row, Sequence) or isinstance(row, str) or len(row) < 5:
            continue
        try:
            found.append((float(row[0]) / 1000.0, float(row[4])))
        except (TypeError, ValueError):
            continue
    return found


class SpotClient:
    def __init__(self, http: JsonHttp, *, base_url: str = SPOT_URL) -> None:
        self.http = http
        self.base_url = base_url

    async def seconds(
        self, symbol: str, *, start: float, end: float
    ) -> list[tuple[float, float]]:
        """One-second closes of ``symbol`` in ``[start, end)``, oldest first."""
        found: list[tuple[float, float]] = []
        cursor = start
        while cursor < end:
            payload = await self.http.get_json(
                build_url(
                    self.base_url,
                    "/api/v3/klines",
                    {
                        "symbol": symbol,
                        "interval": "1s",
                        "startTime": int(cursor * 1000),
                        "endTime": int(end * 1000) - 1,
                        "limit": KLINES_LIMIT,
                    },
                )
            )
            candles = [c for c in parse_klines(payload) if cursor <= c[0] < end]
            if not candles:
                break
            found.extend(candles)
            cursor = candles[-1][0] + 1.0
        return found


__all__ = ["KLINES_LIMIT", "SPOT_URL", "SpotClient", "parse_klines"]
