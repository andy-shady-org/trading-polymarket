from __future__ import annotations

from trading_core.strategy.pipeline import Candidate

from trading_polymarket.catalogue import BookCache, MarketCatalogue
from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.news import NewsClient
from trading_polymarket.config import MomentumLane
from trading_polymarket.strategies.common import KEY_LANE, KEY_MARKET
from trading_polymarket.strategies.momentum import MomentumAnalyst, MomentumScout
from trading_polymarket.tests.support.factories import (
    NO,
    NOW,
    YES,
    book_payload,
    gamma_market,
    iso,
    market,
)
from trading_polymarket.tests.support.fakes import Clock, FakeTransport, fake_http

LANE = MomentumLane(enabled=True)
FAR = iso(NOW + 100 * 3600)


async def discover(markets: list[dict]) -> list[Candidate]:
    transport = FakeTransport({"/markets/keyset": {"markets": markets}})
    gamma = GammaClient(fake_http(transport))
    scout = MomentumScout(gamma, MarketCatalogue(gamma), LANE, clock=Clock(NOW))
    return list(await scout.discover())


async def test_scout_follows_the_direction_of_the_move() -> None:
    found = await discover(
        [
            gamma_market(oneHourPriceChange=0.10, endDate=FAR),
            gamma_market(
                id="2", yes="5" * 30, no="6" * 30, oneHourPriceChange=-0.2, endDate=None
            ),
        ]
    )
    assert [c.instrument_id for c in found] == ["6" * 30, YES]
    assert found[1].data["move_1h"] == 0.1 and found[1].data[KEY_LANE] == "momentum"


async def test_scout_skips_small_moves_soon_closing_and_bands() -> None:
    assert await discover([gamma_market(oneHourPriceChange=0.01, endDate=FAR)]) == []
    soon = iso(NOW + 10 * 3600)
    assert await discover([gamma_market(oneHourPriceChange=0.2, endDate=soon)]) == []
    assert (
        await discover(
            [gamma_market(oneHourPriceChange=0.2, endDate=FAR, bestAsk=0.95)]
        )
        == []
    )


def analyst(payload: dict, news: NewsClient | None = None) -> MomentumAnalyst:
    books = BookCache(ClobClient(fake_http(FakeTransport({"/book": payload}))))
    return MomentumAnalyst(books, LANE, news=news, clock=Clock(NOW))


def candidate() -> Candidate:
    return Candidate(
        NO,
        name="m",
        data={KEY_LANE: "momentum", KEY_MARKET: market(), "move_1h": -0.12},
    )


async def test_analyst_buys_a_small_fixed_amount() -> None:
    signal = await analyst(book_payload(asks=[(0.40, 100)])).evaluate(candidate(), {})
    assert signal is not None and signal.notional == LANE.min_notional
    assert signal.limit_price == 0.41 and signal.edge is None
    assert "news_6h" not in signal.metrics and signal.metrics["move_1h"] == -0.12


async def test_analyst_records_news_attention_and_survives_news_errors() -> None:
    rss = (
        "<rss><channel><item><title>x</title>"
        "<pubDate>Wed, 28 Oct 2026 11:00:00 GMT</pubDate></item></channel></rss>"
    )
    news = NewsClient(fake_http(FakeTransport({"/rss/search": rss})))
    signal = await analyst(book_payload(asks=[(0.40, 100)]), news).evaluate(
        candidate(), {}
    )
    assert signal is not None and signal.metrics["news_6h"] == 1
    broken = NewsClient(
        fake_http(FakeTransport({"/rss/search": OSError("x")}), max_retries=0)
    )
    signal = await analyst(book_payload(asks=[(0.40, 100)]), broken).evaluate(
        candidate(), {}
    )
    assert signal is not None and "news_6h" not in signal.metrics


async def test_analyst_declines_thin_or_dear_books() -> None:
    assert await analyst(book_payload(asks=[])).evaluate(candidate(), {}) is None
    assert (
        await analyst(book_payload(asks=[(0.90, 100)])).evaluate(candidate(), {})
        is None
    )
    assert (
        await analyst(book_payload(asks=[(0.40, 1)])).evaluate(candidate(), {}) is None
    )
