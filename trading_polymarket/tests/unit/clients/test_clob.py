from __future__ import annotations

import json

import pytest

from trading_polymarket.clients.clob import (
    BOOKS_BATCH,
    REWARDS_END_CURSOR,
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


async def test_rewards_markets_pages_until_the_end_cursor() -> None:
    def page(url: str) -> object:
        if "next_cursor=NTAw" in url:
            return {
                "data": [{"condition_id": "0xb"}],
                "next_cursor": REWARDS_END_CURSOR,
            }
        return {"data": [{"condition_id": "0xa"}, "not a row"], "next_cursor": "NTAw"}

    transport = FakeTransport({"/rewards/markets/current": page})
    found = await client(transport).rewards_markets()
    assert [r["condition_id"] for r in found] == ["0xa", "0xb"]
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    "payload",
    [
        ["not a mapping"],
        {"data": [], "next_cursor": "NTAw"},
        {"data": "x", "next_cursor": "NTAw"},
        {"data": [{"condition_id": "0xa"}]},
    ],
)
async def test_rewards_markets_stop_on_odd_pages(payload: object) -> None:
    transport = FakeTransport({"/rewards/markets/current": payload})
    await client(transport).rewards_markets()
    assert len(transport.calls) == 1


async def test_rewards_markets_page_limit() -> None:
    transport = FakeTransport(
        {
            "/rewards/markets/current": {
                "data": [{"condition_id": "0x"}],
                "next_cursor": "X",
            }
        }
    )
    found = await client(transport).rewards_markets(max_pages=3)
    assert len(found) == 3 and len(transport.calls) == 3


async def test_books_reads_in_batches_and_skips_tokens_without_a_book() -> None:
    def answer(url: str) -> list[object]:
        return [
            book_payload("a", bids=[(0.4, 10)], asks=[(0.6, 10)]),
            book_payload("b"),
            {"asks": []},  # no asset id: dropped
            "junk",
        ]

    transport = FakeTransport({"/books": answer})
    clob = ClobClient(fake_http(transport))
    tokens = ["a", "b", "a", *[f"x{i}" for i in range(BOOKS_BATCH)]]
    found = await clob.books(tokens)
    assert sorted(found) == ["a", "b"]
    assert found["a"].best_ask == 0.6
    assert transport.count("/books") == 2  # 502 distinct tokens: two requests
    first = json.loads(transport.bodies[0])
    assert len(first) == BOOKS_BATCH and first[0] == {"token_id": "a"}
    assert len(json.loads(transport.bodies[1])) == 2
    assert await clob.books([]) == {}


async def test_books_ignores_a_reply_that_is_not_a_list() -> None:
    clob = ClobClient(fake_http(FakeTransport({"/books": {"error": "x"}})))
    assert await clob.books(["a"]) == {}
