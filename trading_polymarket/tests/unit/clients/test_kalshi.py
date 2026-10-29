from __future__ import annotations

import pytest

from trading_polymarket.clients.kalshi import (
    KALSHI_URL,
    STATUS_SETTLED,
    Candle,
    KalshiClient,
    KalshiEvent,
    KalshiMarket,
    candle_at,
    dollars,
    parse_candles,
)
from trading_polymarket.tests.support.factories import (
    FED_MEETING,
    fed_kalshi_event,
    kalshi_market,
)
from trading_polymarket.tests.support.fakes import FakeTransport, Sequenced, fake_http


def client(transport: FakeTransport) -> KalshiClient:
    return KalshiClient(fake_http(transport), base_url="https://k.test")


def test_dollars() -> None:
    assert dollars("0.2500") == 0.25 and dollars(1) == 1.0
    assert dollars(None) is None and dollars("") is None and dollars("x") is None
    assert dollars([1]) is None


def test_market_from_api() -> None:
    m = KalshiMarket.from_api(kalshi_market())
    assert (
        m.ticker == "KXFEDDECISION-26NOV-H0" and m.event_ticker == "KXFEDDECISION-26NOV"
    )
    assert m.yes_label == "Fed maintains rate"
    assert (m.yes_bid, m.yes_ask, m.last) == (0.6, 0.62, 0.61)
    assert m.mid == pytest.approx(0.61) and m.spread == pytest.approx(0.02)
    assert m.volume_24h == 25000 and m.open_interest == 100000
    assert m.close_time == FED_MEETING - 3600 and m.settled_yes is None


def test_market_with_an_empty_side_and_fallback_fields() -> None:
    m = KalshiMarket.from_api(
        {
            "ticker": "T",
            "subtitle": "old",
            "yes_bid_dollars": "0.0000",
            "yes_ask_dollars": "1.0000",
            "volume_24h": 5,
            "result": "yes",
        }
    )
    assert m.yes_label == "old" and m.yes_bid is None and m.yes_ask is None
    assert m.mid is None and m.spread is None
    assert m.volume_24h == 5 and m.open_interest == 0 and m.close_time is None
    assert m.settled_yes is True
    assert KalshiMarket.from_api({"result": "no"}).settled_yes is False


def test_event_from_api_skips_junk_markets() -> None:
    raw = fed_kalshi_event()
    raw["markets"].append("junk")
    event = KalshiEvent.from_api(raw)
    assert event.series_ticker == "KXFEDDECISION" and len(event.markets) == 5
    assert KalshiEvent.from_api({}).markets == ()


def test_candles() -> None:
    payload = {
        "candlesticks": [
            {"end_period_ts": 200, "yes_bid": {"close_dollars": "0.40"}},
            {
                "end_period_ts": 100,
                "yes_bid": {"close_dollars": "0.30"},
                "yes_ask": {"close_dollars": "0.32"},
            },
            {
                "end_period_ts": 300,
                "yes_bid": {"close_dollars": "0"},
                "yes_ask": {"close_dollars": "1"},
            },
            {"yes_bid": {}},
            "junk",
        ]
    }
    candles = parse_candles(payload)
    assert [c.t for c in candles] == [100, 200, 300]
    assert candles[0].mid == pytest.approx(0.31)
    assert candles[1].yes_ask is None and candles[1].mid is None
    assert candles[2].yes_bid is None and candles[2].yes_ask is None
    assert parse_candles([]) == [] and parse_candles({"candlesticks": None}) == []
    assert candle_at(candles, 99) is None
    assert candle_at(candles, 250) == candles[1]
    assert candle_at(candles, 1000) == candles[2]
    assert Candle(1, None, 0.5).mid is None


async def test_events_follow_the_cursor() -> None:
    transport = FakeTransport(
        {
            "/events?": Sequenced(
                {"events": [fed_kalshi_event(), "junk"], "cursor": "abc"},
                {"events": [fed_kalshi_event()], "cursor": ""},
            )
        }
    )
    events = await client(transport).events(series_ticker="KXFEDDECISION")
    assert len(events) == 2
    assert "series_ticker=KXFEDDECISION" in transport.calls[0]
    assert "status=open" in transport.calls[0]
    assert "cursor=abc" in transport.calls[1]


async def test_events_stop_on_an_empty_page_or_the_page_limit() -> None:
    transport = FakeTransport({"/events?": {"events": [], "cursor": "more"}})
    assert await client(transport).events(status=STATUS_SETTLED) == []
    assert transport.count("/events?") == 1
    looping = FakeTransport(
        {"/events?": {"events": [fed_kalshi_event()], "cursor": "c"}}
    )
    assert len(await client(looping).events(max_pages=3)) == 3
    odd = FakeTransport({"/events?": ["not", "a", "mapping"]})
    assert await client(odd).events() == []


async def test_event_market_and_candlesticks() -> None:
    transport = FakeTransport(
        {
            "/events/KXFEDDECISION-26NOV": {"event": fed_kalshi_event()},
            "/markets/KXFEDDECISION-26NOV-H0": {"market": kalshi_market()},
            "/candlesticks": {
                "candlesticks": [
                    {
                        "end_period_ts": 100,
                        "yes_bid": {"close_dollars": "0.3"},
                        "yes_ask": {"close_dollars": "0.4"},
                    }
                ]
            },
        }
    )
    k = client(transport)
    assert len((await k.event("KXFEDDECISION-26NOV")).markets) == 5
    assert (await k.market("KXFEDDECISION-26NOV-H0")).yes_bid == 0.6
    candles = await k.candlesticks("KXFEDDECISION", "X", start=10.5, end=99.9)
    assert candles[0].yes_ask == 0.4
    url = transport.calls[-1]
    assert "/series/KXFEDDECISION/markets/X/candlesticks" in url
    assert "start_ts=10" in url and "end_ts=99" in url and "period_interval=60" in url
    empty = client(FakeTransport({"/markets/": [], "/events/": []}))
    assert (await empty.market("X")).ticker == ""
    assert (await empty.event("X")).markets == ()


def test_default_base_url() -> None:
    assert KalshiClient(fake_http()).base_url == KALSHI_URL
