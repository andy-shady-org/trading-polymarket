from __future__ import annotations

import pytest

from trading_polymarket.book import OrderBook, Walk
from trading_polymarket.tests.support.factories import (
    NOW,
    YES,
    book,
    book_payload,
    fixture,
)


def test_from_clob_orders_both_sides_best_first() -> None:
    b = book()
    assert [lv.price for lv in b.bids] == [0.59, 0.58]
    assert [lv.price for lv in b.asks] == [0.61, 0.62, 0.63]
    assert b.best_bid == 0.59 and b.best_ask == 0.61
    assert b.mid == pytest.approx(0.60) and b.spread == pytest.approx(0.02)
    assert b.timestamp == pytest.approx(NOW)
    assert b.tick_size == 0.01 and b.min_order_size == 5
    assert b.last_trade_price == 0.6 and b.token_id == YES


def test_real_fixture_parses() -> None:
    b = OrderBook.from_clob(fixture("book.json"))
    assert b.asks and b.bids
    assert b.best_ask is not None and b.best_bid is not None
    assert b.best_ask > b.best_bid


def test_malformed_levels_and_fields_are_skipped() -> None:
    payload = book_payload(
        bids=[(0.5, 10)],
        asks=[],
        tick_size="x",
        timestamp="bad",
        last_trade_price=None,
    )
    payload["bids"] += [
        {"price": "x", "size": "1"},
        {"price": "0"},
        {"price": "0.4", "size": "0"},
        "junk",
        {},
    ]
    payload["asks"] = None
    b = OrderBook.from_clob(payload)
    assert len(b.bids) == 1 and b.asks == ()
    assert b.timestamp is None and b.tick_size == 0.01
    assert b.last_trade_price is None
    assert b.best_ask is None and b.mid is None and b.spread is None
    no_stamp = OrderBook.from_clob({"bids": [], "asks": []})
    assert no_stamp.timestamp is None and no_stamp.token_id == ""


def test_from_levels() -> None:
    b = OrderBook.from_levels("t", bids=[(0.4, 1), (0.5, 1)], asks=[(0.7, 1), (0.6, 1)])
    assert b.best_bid == 0.5 and b.best_ask == 0.6


def test_depth_and_imbalance() -> None:
    b = book()
    assert b.depth("ask", within=0.011) == pytest.approx(0.61 * 20 + 0.62 * 50)
    assert b.depth("bid", within=0.0) == pytest.approx(0.59 * 50)
    assert b.imbalance(within=0.0) == pytest.approx(
        (0.59 * 50 - 0.61 * 20) / (0.59 * 50 + 0.61 * 20)
    )
    empty = OrderBook.from_levels("t", [], [])
    assert empty.depth("bid", within=1) == 0.0 and empty.imbalance() == 0.0


def test_walk_buy_spends_notional_across_levels_within_limit() -> None:
    b = book()
    walk = b.walk_buy(0.61 * 20 + 0.62 * 10)
    assert walk.size == pytest.approx(30)
    assert walk.levels == 2 and walk.worst_price == 0.62
    assert walk.average_price == pytest.approx((0.61 * 20 + 0.62 * 10) / 30)
    limited = b.walk_buy(1000, limit=0.61)
    assert limited.size == pytest.approx(20) and limited.levels == 1
    assert b.walk_buy(1000, limit=0.5).size == 0


def test_walk_sell_fills_into_bids() -> None:
    b = book()
    walk = b.walk_sell(60)
    assert walk.size == pytest.approx(60)
    assert walk.notional == pytest.approx(0.59 * 50 + 0.58 * 10)
    assert b.walk_sell(500, limit=0.59).size == pytest.approx(50)
    assert b.walk_sell(10, limit=0.9).size == 0


def test_empty_walk() -> None:
    walk = Walk(0.0, 0.0)
    assert walk.average_price is None and walk.worst_price is None
    assert walk.levels == 0
