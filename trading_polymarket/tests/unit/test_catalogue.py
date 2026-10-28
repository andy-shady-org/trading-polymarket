from __future__ import annotations

import pytest

from trading_polymarket.catalogue import BookCache, MarketCatalogue
from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.tests.support.factories import (
    NO,
    NOW,
    YES,
    book_payload,
    gamma_market,
    market,
)
from trading_polymarket.tests.support.fakes import Clock, FakeTransport, fake_http


@pytest.mark.regression("TP-3")
async def test_catalogue_caches_and_refetches_when_stale() -> None:
    transport = FakeTransport({"/markets?": [gamma_market()]})
    clock = Clock(NOW)
    cat = MarketCatalogue(
        GammaClient(fake_http(transport), base_url="https://g.test"),
        ttl=60,
        clock=clock,
    )
    assert cat.cached(YES) is None
    first = await cat.get(YES)
    assert first is not None and cat.cached(NO) is first and len(cat) == 1
    await cat.get(YES)
    assert transport.count("/markets?") == 1
    clock.advance(61)
    await cat.get(YES)
    assert transport.count("/markets?") == 2
    await cat.get(YES, max_age=0)
    assert transport.count("/markets?") == 3


async def test_catalogue_keeps_old_entry_when_lookup_finds_nothing() -> None:
    transport = FakeTransport({"/markets?": []})
    clock = Clock(NOW)
    cat = MarketCatalogue(GammaClient(fake_http(transport)), ttl=1, clock=clock)
    assert await cat.get(YES) is None
    cat.put([market()])
    clock.advance(5)
    assert (await cat.get(YES)) is not None


async def test_catalogue_refresh() -> None:
    transport = FakeTransport({"/markets?": [gamma_market()]})
    cat = MarketCatalogue(GammaClient(fake_http(transport)))
    await cat.refresh([YES])
    assert cat.cached(YES) is not None


async def test_book_cache_ttl_and_forget() -> None:
    transport = FakeTransport({"/book": book_payload()})
    clock = Clock(NOW)
    books = BookCache(ClobClient(fake_http(transport)), ttl=5, clock=clock)
    assert books.cached(YES) is None
    await books.get(YES)
    await books.get(YES)
    assert transport.count("/book") == 1 and books.cached(YES) is not None
    await books.get(YES, max_age=0)
    assert transport.count("/book") == 2
    clock.advance(6)
    await books.get(YES)
    assert transport.count("/book") == 3
    books.forget(YES)
    assert books.cached(YES) is None
