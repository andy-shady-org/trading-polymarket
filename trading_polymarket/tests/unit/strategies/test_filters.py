from __future__ import annotations

import pytest
from trading_core.strategy.pipeline import Candidate

from trading_polymarket.catalogue import BookCache
from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.config import PolymarketSettings
from trading_polymarket.strategies.common import KEY_LANE, KEY_MARKET
from trading_polymarket.strategies.filters import BookFilter, MarketStateFilter
from trading_polymarket.tests.support.factories import (
    NOW,
    YES,
    book_payload,
    market,
    resolved,
)
from trading_polymarket.tests.support.fakes import Clock, FakeTransport, fake_http

SETTINGS = PolymarketSettings.from_mapping(
    {"favourite": {"enabled": True, "min_volume_24h": 1000, "min_liquidity": 500}}
)


def candidate(m: object = None, lane: str = "favourite") -> Candidate:
    return Candidate(YES, data={KEY_LANE: lane, KEY_MARKET: m or market()})


async def test_market_state_accepts_and_records_metrics() -> None:
    verdict = await MarketStateFilter(SETTINGS, clock=Clock(NOW)).screen(candidate())
    assert verdict.passed
    assert verdict.metrics["hours_to_close"] == pytest.approx(24)
    assert verdict.metrics["fee_rate"] == 0.05
    no_end = await MarketStateFilter(SETTINGS).screen(candidate(market(endDate=None)))
    assert no_end.metrics["hours_to_close"] is None


@pytest.mark.parametrize(
    ("m", "reason"),
    [
        (resolved(), "not open"),
        (market(acceptingOrders=False), "not open"),
        (market(volume24hr=10), "24h volume"),
        (market(liquidityNum=10), "liquidity"),
    ],
)
async def test_market_state_rejections(m: object, reason: str) -> None:
    verdict = await MarketStateFilter(SETTINGS).screen(candidate(m))
    assert not verdict.passed and reason in verdict.reason


async def test_market_state_needs_a_market() -> None:
    with pytest.raises(ValueError):
        await MarketStateFilter(SETTINGS).screen(Candidate(YES, data={KEY_LANE: "x"}))


def book_filter(payload: object) -> BookFilter:
    transport = FakeTransport({"/book": payload} if payload is not None else {})
    return BookFilter(SETTINGS, BookCache(ClobClient(fake_http(transport))))


async def test_book_filter_accepts_a_tight_deep_book() -> None:
    payload = book_payload(bids=[(0.60, 500)], asks=[(0.61, 500)])
    verdict = await book_filter(payload).screen(candidate())
    assert verdict.passed and verdict.metrics["spread"] == pytest.approx(0.01)
    assert verdict.metrics["ask_depth"] == pytest.approx(305)


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (None, "no order book"),
        (book_payload(bids=[]), "one-sided"),
        (book_payload(bids=[(0.40, 500)], asks=[(0.61, 500)]), "spread"),
        (book_payload(bids=[(0.60, 500)], asks=[(0.61, 10)]), "ask depth"),
    ],
)
async def test_book_filter_rejections(payload: object, reason: str) -> None:
    verdict = await book_filter(payload).screen(candidate())
    assert not verdict.passed and reason in verdict.reason
