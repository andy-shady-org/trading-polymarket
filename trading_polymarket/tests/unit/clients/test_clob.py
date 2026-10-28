from __future__ import annotations

import pytest

from trading_polymarket.clients.clob import (
    BookUnavailable,
    ClobClient,
    PricePoint,
    parse_history,
    price_at,
)
from trading_polymarket.clients.http import HttpError, Response
from trading_polymarket.tests.support.factories import YES, book_payload, fixture
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http


def client(transport: FakeTransport) -> ClobClient:
    return ClobClient(fake_http(transport, max_retries=0), base_url="https://c.test")


async def test_book_parses_and_fills_missing_token_id() -> None:
    payload = book_payload()
    payload.pop("asset_id")
    book = await client(FakeTransport({"/book": payload})).book(YES)
    assert book.token_id == YES and book.best_ask == 0.61


async def test_book_unavailable_for_404_and_bad_payload() -> None:
    with pytest.raises(BookUnavailable):
        await client(FakeTransport()).book(YES)
    with pytest.raises(BookUnavailable):
        await client(FakeTransport({"/book": [1, 2]})).book(YES)
    with pytest.raises(HttpError):
        await client(FakeTransport({"/book": Response(500, b"")})).book(YES)


def test_parse_history_and_price_at() -> None:
    points = parse_history(
        {"history": [{"t": 3, "p": 0.3}, {"t": 1, "p": 0.1}, {"t": "x"}, "bad"]}
    )
    assert points == [PricePoint(1, 0.1), PricePoint(3, 0.3)]
    assert parse_history([{"t": 1, "p": 0.5}]) == [PricePoint(1, 0.5)]
    assert parse_history(None) == []
    assert price_at(points, 0) is None
    assert price_at(points, 2) == 0.1
    assert price_at(points, 3) == 0.3


async def test_prices_history_windows_and_trims() -> None:
    payload = fixture("prices_history.json")
    transport = FakeTransport({"/prices-history": payload})
    c = client(transport)
    everything = await c.prices_history(YES, fidelity=60)
    assert len(everything) == len(payload["history"])
    assert "interval=max" in transport.calls[0] and "fidelity=60" in transport.calls[0]
    middle = everything[len(everything) // 2].t
    trimmed = await c.prices_history(YES, start=middle, end=middle)
    assert [p.t for p in trimmed] == [middle]
    assert f"startTs={int(middle)}&endTs={int(middle)}" in transport.calls[-1]
    assert "interval" not in transport.calls[-1]
    await c.prices_history(YES, start=100)
    assert "startTs=100&endTs=604900" in transport.calls[-1]
