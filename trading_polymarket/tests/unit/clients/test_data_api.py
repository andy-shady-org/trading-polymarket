"""Unit tests for ``clients/data_api.py``: a market's trades (FEAT-146)."""

from __future__ import annotations

from typing import Any

from trading_polymarket.clients.data_api import DataApiClient, TradePrint
from trading_polymarket.tests.support.fakes import FakeTransport, Sequenced, fake_http


def row(t: float, **extra: Any) -> dict[str, Any]:
    return {
        "timestamp": t,
        "outcome_index": 1,
        "side": "buy",
        "price": 0.04,
        "size": 25.0,
        "proxy_wallet": "0xABC",
        **extra,
    }


def client(transport: FakeTransport) -> DataApiClient:
    return DataApiClient(fake_http(transport), base_url="https://d.test")


def test_a_row_is_read_or_refused() -> None:
    assert TradePrint.from_api(row(5)) == TradePrint(5.0, 1, "BUY", 0.04, 25.0, "0xabc")
    anonymous = TradePrint.from_api(row(5, proxy_wallet=None))
    assert anonymous is not None and anonymous.wallet == ""
    assert TradePrint.from_api(row(5, side="HOLD")) is None
    assert TradePrint.from_api(row(5, price="x")) is None
    assert TradePrint.from_api({"side": "BUY"}) is None


async def test_pages_follow_the_cursor_and_come_back_oldest_first() -> None:
    transport = FakeTransport(
        {
            "/v2/trades": Sequenced(
                {
                    "data": [row(9), row(7, side="SELL"), "bad", row(7, price=None)],
                    "pagination": {"has_more": True, "next_cursor": "c2"},
                },
                {"data": [row(3), row(7, outcome_index=0)], "pagination": {}},
            )
        }
    )
    prints = await client(transport).trades("0xmarket")
    # Same-second prints keep the order they were made in (the API's reversed).
    assert [(p.timestamp, p.side, p.outcome_index) for p in prints] == [
        (3.0, "BUY", 1),
        (7.0, "BUY", 0),
        (7.0, "SELL", 1),
        (9.0, "BUY", 1),
    ]
    assert "condition_id=0xmarket" in transport.calls[0]
    assert "cursor" not in transport.calls[0] and "cursor=c2" in transport.calls[1]


async def test_paging_stops_on_odd_answers_and_the_page_cap() -> None:
    odd = FakeTransport({"/v2/trades": ["not", "a", "mapping"]})
    assert await client(odd).trades("m") == []
    empty = FakeTransport(
        {
            "/v2/trades": {
                "data": "x",
                "pagination": {"has_more": True, "next_cursor": "c"},
            }
        }
    )
    assert await client(empty).trades("m") == [] and len(empty.calls) == 1
    no_page = FakeTransport({"/v2/trades": {"data": [row(1)], "pagination": "x"}})
    assert len(await client(no_page).trades("m")) == 1
    endless = FakeTransport(
        {
            "/v2/trades": {
                "data": [row(1)],
                "pagination": {"has_more": True, "next_cursor": "c"},
            }
        }
    )
    assert len(await client(endless).trades("m", max_pages=3)) == 3
    assert len(endless.calls) == 3
