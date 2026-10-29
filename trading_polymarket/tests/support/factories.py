"""Builders for API payloads and domain objects used across the suite."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_polymarket.book import OrderBook
from trading_polymarket.markets import Market

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC).timestamp()
YES = "1" * 40
NO = "2" * 40
CONDITION = "0x" + "ab" * 32


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def iso(moment: float) -> str:
    return datetime.fromtimestamp(moment, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def gamma_market(**overrides: Any) -> dict[str, Any]:
    """A Gamma ``/markets`` item (JSON-string fields as the API sends them)."""
    yes = overrides.pop("yes", YES)
    no = overrides.pop("no", NO)
    prices = overrides.pop("prices", None)
    data: dict[str, Any] = {
        "id": "100",
        "question": "Will it happen?",
        "conditionId": CONDITION,
        "slug": "will-it-happen",
        "endDate": iso(NOW + 24 * 3600),
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(prices or ["0.6", "0.4"]),
        "clobTokenIds": json.dumps([yes, no]),
        "volume24hr": 50000,
        "volumeNum": 250000,
        "liquidityNum": 20000,
        "bestBid": 0.59,
        "bestAsk": 0.61,
        "lastTradePrice": 0.6,
        "negRisk": False,
        "feesEnabled": True,
        "feeSchedule": {"rate": 0.05, "exponent": 1, "takerOnly": True},
        "orderPriceMinTickSize": 0.01,
        "orderMinSize": 5,
        "closed": False,
        "active": True,
        "acceptingOrders": True,
        "oneHourPriceChange": 0.0,
        "oneDayPriceChange": 0.0,
    }
    data.update(overrides)
    return data


def market(**overrides: Any) -> Market:
    event = overrides.pop("event", None)
    return Market.from_gamma(gamma_market(**overrides), event=event)


def resolved(winner: int = 0, **overrides: Any) -> Market:
    prices = ["1", "0"] if winner == 0 else ["0", "1"]
    return market(prices=prices, closed=True, acceptingOrders=False, **overrides)


def book_payload(
    token: str = YES,
    bids: list[tuple[float, float]] | None = None,
    asks: list[tuple[float, float]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """A CLOB ``/book`` reply (bids ascending, asks descending: best last)."""
    bids = [(0.58, 100.0), (0.59, 50.0)] if bids is None else bids
    asks = [(0.63, 100.0), (0.62, 50.0), (0.61, 20.0)] if asks is None else asks
    return {
        "asset_id": token,
        "timestamp": str(int(NOW * 1000)),
        "bids": [{"price": str(p), "size": str(s)} for p, s in sorted(bids)],
        "asks": [
            {"price": str(p), "size": str(s)} for p, s in sorted(asks, reverse=True)
        ],
        "tick_size": "0.01",
        "min_order_size": "5",
        "last_trade_price": "0.60",
        **extra,
    }


def book(
    token: str = YES,
    bids: list[tuple[float, float]] | None = None,
    asks: list[tuple[float, float]] | None = None,
) -> OrderBook:
    return OrderBook.from_clob(book_payload(token, bids, asks))


def weather_markets(
    city: str = "Dallas",
    icao: str = "KDAL",
    unit: str = "F",
    titles: list[str] | None = None,
    end: float | None = None,
    asks: list[float] | None = None,
) -> list[dict[str, Any]]:
    titles = titles or ["73°F or below", "74-75°F", "76-77°F", "78°F or higher"]
    asks = asks or [0.10] * len(titles)
    out = []
    for index, title in enumerate(titles):
        ask = asks[index]
        out.append(
            gamma_market(
                id=str(500 + index),
                question=f"Will the highest temperature in {city} be {title}?",
                groupItemTitle=title,
                yes=f"{index + 1}" * 30,
                no=f"9{index + 1}" * 15,
                bestAsk=ask,
                bestBid=max(0.0, round(ask - 0.02, 4)),
                feesEnabled=False,
                feeSchedule=None,
                endDate=iso(end if end is not None else NOW),
                description=(
                    f"resolves on the highest temperature reported at {city} "
                    f"Airport ({icao}) in the hourly METAR remark."
                ),
                volume24hr=500,
                liquidityNum=300,
            )
        )
    return out


def weather_event(
    city: str = "Dallas",
    day: str = "October 28",
    **kwargs: Any,
) -> dict[str, Any]:
    return {
        "id": "9001",
        "title": f"Highest temperature in {city} on {day}?",
        "description": "",
        "endDate": iso(kwargs.get("end") or NOW),
        "markets": weather_markets(city=city, **kwargs),
        "tags": [{"slug": "highest-temperature", "label": "Highest temperature"}],
    }


def forecast_payload(
    *,
    day: str = "2026-10-28",
    maxima: dict[str, float] | None = None,
    hourly: dict[str, list[float]] | None = None,
    timezone: str = "America/Chicago",
    offset: int = -18000,
) -> dict[str, Any]:
    """An Open-Meteo multi-model reply with one day of hourly values."""
    maxima = maxima or {"ecmwf_ifs025": 24.0, "gfs_seamless": 25.0}
    hours = [f"{day}T{h:02d}:00" for h in range(24)]
    payload: dict[str, Any] = {
        "timezone": timezone,
        "utc_offset_seconds": offset,
        "daily": {"time": [day]},
        "hourly": {"time": hours},
    }
    for model, value in maxima.items():
        payload["daily"][f"temperature_2m_max_{model}"] = [value]
        series = (hourly or {}).get(model) or [
            value - abs(15 - h) * 0.5 for h in range(24)
        ]
        payload["hourly"][f"temperature_2m_{model}"] = series
    return payload


def metar_row(
    obs_time: float,
    raw: str = "METAR KDAL 281253Z 15008KT 10SM CLR 19/14 A3014 RMK T01940144",
    icao: str = "KDAL",
    kind: str = "METAR",
) -> dict[str, Any]:
    return {"icaoId": icao, "obsTime": obs_time, "rawOb": raw, "metarType": kind}


def history_row(
    *,
    market_id: str = "1",
    winner: int = 0,
    end_time: float = NOW,
    prices: list[tuple[float, float]] | None = None,
    fee_rate: float = 0.0,
) -> dict[str, Any]:
    prices = prices or [(end_time - 80 * 3600, 0.85), (end_time - 2 * 3600, 0.9)]
    return {
        "market_id": market_id,
        "question": f"market {market_id}",
        "token_ids": [f"{market_id}1" * 4, f"{market_id}2" * 4],
        "outcomes": ["Yes", "No"],
        "winner": winner,
        "end_time": end_time,
        "volume": 10000,
        "fee_rate": fee_rate,
        "fee_exponent": 1,
        "history": [[t, p] for t, p in prices],
    }


# -- Kalshi and the Fed decision lane ------------------------------------------
FED_MEETING = NOW + 10 * 86400  # the meeting statement, ~18:00 UTC
FED_BUCKETS = (
    # Polymarket bucket, Kalshi subtitle, Kalshi code
    ("50+ bps decrease", "Cut >25bps", "C26"),
    ("25 bps decrease", "Cut 25bps", "C25"),
    ("No change", "Fed maintains rate", "H0"),
    ("25 bps increase", "Hike 25bps", "H25"),
    ("50+ bps increase", "Hike >25bps", "H26"),
)


def kalshi_market(
    ticker: str = "KXFEDDECISION-26NOV-H0", **overrides: Any
) -> dict[str, Any]:
    """A Kalshi ``/markets`` item (prices as dollar strings)."""
    data: dict[str, Any] = {
        "ticker": ticker,
        "event_ticker": ticker.rsplit("-", 1)[0],
        "title": "Fed decision in Nov 2026?",
        "yes_sub_title": "Fed maintains rate",
        "yes_bid_dollars": "0.6000",
        "yes_ask_dollars": "0.6200",
        "last_price_dollars": "0.6100",
        "volume_24h_fp": "25000.00",
        "open_interest_fp": "100000.00",
        "close_time": iso(FED_MEETING - 3600),
        "status": "active",
        "result": "",
    }
    data.update(overrides)
    return data


def fed_kalshi_event(
    quotes: dict[str, tuple[str, str]] | None = None, *, meeting: float = FED_MEETING
) -> dict[str, Any]:
    """Kalshi's KXFEDDECISION event for a meeting: ``code -> (bid, ask)``."""
    quotes = quotes or {"H0": ("0.6000", "0.6200"), "H25": ("0.3500", "0.3700")}
    event = "KXFEDDECISION-26NOV"
    markets = []
    for _, subtitle, code in FED_BUCKETS:
        bid, ask = quotes.get(code, ("0.0000", "0.0100"))
        markets.append(
            kalshi_market(
                f"{event}-{code}",
                yes_sub_title=subtitle,
                yes_bid_dollars=bid,
                yes_ask_dollars=ask,
                close_time=iso(meeting - 3600),
            )
        )
    return {
        "event_ticker": event,
        "series_ticker": "KXFEDDECISION",
        "title": "Fed decision in Nov 2026",
        "markets": markets,
    }


def fed_pm_event(
    asks: dict[str, float] | None = None,
    *,
    meeting: float = FED_MEETING,
    title: str = "Fed Decision in November?",
) -> dict[str, Any]:
    """Polymarket's "Fed Decision in <Month>?" event: ``bucket -> Yes ask``."""
    asks = asks or {"No change": 0.55, "25 bps increase": 0.36}
    markets = []
    for index, (bucket, _, _) in enumerate(FED_BUCKETS):
        ask = asks.get(bucket, 0.01)
        markets.append(
            gamma_market(
                id=str(700 + index),
                question=f"Will the Fed {bucket}?",
                groupItemTitle=bucket,
                yes=f"7{index}" * 20,
                no=f"8{index}" * 20,
                bestAsk=ask,
                bestBid=round(max(0.0, ask - 0.01), 4),
                feesEnabled=False,
                feeSchedule=None,
                negRisk=True,
                endDate=iso(meeting),
            )
        )
    return {"id": "9000", "title": title, "slug": "fed-decision", "markets": markets}


def fed_yes(bucket: str) -> str:
    index = [b for b, _, _ in FED_BUCKETS].index(bucket)
    return f"7{index}" * 20


def fed_no(bucket: str) -> str:
    index = [b for b, _, _ in FED_BUCKETS].index(bucket)
    return f"8{index}" * 20


__all__ = [
    "CONDITION",
    "FED_BUCKETS",
    "FED_MEETING",
    "FIXTURES",
    "NO",
    "NOW",
    "YES",
    "book",
    "book_payload",
    "fed_kalshi_event",
    "fed_no",
    "fed_pm_event",
    "fed_yes",
    "fixture",
    "forecast_payload",
    "gamma_market",
    "history_row",
    "iso",
    "kalshi_market",
    "market",
    "metar_row",
    "resolved",
    "weather_event",
    "weather_markets",
]
