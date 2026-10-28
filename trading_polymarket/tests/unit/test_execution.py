from __future__ import annotations

from typing import Any

import pytest
from trading_core.module.base import ExecutionRefused, OrderRequest, Side

from trading_polymarket.book import Level, Walk
from trading_polymarket.catalogue import BookCache, MarketCatalogue
from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.http import Response
from trading_polymarket.config import PaperSettings
from trading_polymarket.execution import (
    LiveExecutor,
    PaperExecutor,
    floor_to,
    trim_walk,
    walk_fee,
)
from trading_polymarket.fees import FeeSchedule
from trading_polymarket.tests.support.factories import (
    NO,
    NOW,
    YES,
    book_payload,
    gamma_market,
)
from trading_polymarket.tests.support.fakes import Clock, FakeTransport, fake_http


def executor(
    transport: FakeTransport, **paper: Any
) -> tuple[PaperExecutor, FakeTransport]:
    http = fake_http(transport, max_retries=0)
    clock = Clock(NOW)
    cat = MarketCatalogue(GammaClient(http), clock=clock)
    books = BookCache(ClobClient(http), clock=clock)
    return PaperExecutor(cat, books, PaperSettings(**paper), clock=clock), transport


def routes(market: dict | None = None, book: dict | None = None) -> FakeTransport:
    return FakeTransport(
        {
            "/markets?": [market or gamma_market()],
            "/book": book or book_payload(),
        }
    )


def buy(notional: float = 10.0, **kw: Any) -> OrderRequest:
    return OrderRequest(instrument_id=YES, side=Side.BUY, notional=notional, **kw)


def sell(size: float = 10.0, **kw: Any) -> OrderRequest:
    return OrderRequest(instrument_id=YES, side=Side.SELL, size=size, **kw)


def test_helpers() -> None:
    assert floor_to(1.239, 2) == 1.23
    assert floor_to(1.2399999999999, 2) == 1.24  # float noise is not a cent
    walk = Walk(30, 0.61 * 20 + 0.62 * 10, (Level(0.61, 20), Level(0.62, 10)))
    trimmed = trim_walk(walk, 25)
    assert trimmed.size == 25 and trimmed.parts[-1] == Level(0.62, 5)
    assert trim_walk(walk, 0).size == 0
    assert walk_fee(trimmed, FeeSchedule(rate=0.05)) == round(
        20 * 0.05 * 0.61 * 0.39 + 5 * 0.05 * 0.62 * 0.38, 5
    )


async def test_buy_walks_the_live_book_and_charges_the_fee() -> None:
    ex, transport = executor(routes())
    fill = await ex.execute(buy(0.61 * 20 + 0.62 * 10))
    assert fill.side is Side.BUY and fill.simulated
    assert fill.size == pytest.approx(30)
    assert fill.price == pytest.approx((0.61 * 20 + 0.62 * 10) / 30)
    assert fill.costs.components["fee"] == pytest.approx(
        round(20 * 0.05 * 0.61 * 0.39 + 10 * 0.05 * 0.62 * 0.38, 5)
    )
    assert str(fill.reference).startswith("paper-buy-")
    assert fill.metadata["levels"] == 2 and fill.metadata["outcome"] == "Yes"
    assert fill.timestamp == NOW
    assert transport.count("/book") == 1


async def test_buy_respects_limit_and_default_slippage() -> None:
    ex, _ = executor(routes(), max_slippage=0.0)
    fill = await ex.execute(buy(100))
    assert fill.size == pytest.approx(20)  # only the 0.61 level
    ex, _ = executor(routes())
    fill = await ex.execute(buy(100, limit_price=0.62))
    assert fill.size == pytest.approx(70)


async def test_buy_by_size_and_price_cap() -> None:
    ex, _ = executor(routes())
    order = OrderRequest(instrument_id=YES, side=Side.BUY, size=10, limit_price=0.7)
    fill = await ex.execute(order)
    assert fill.size == pytest.approx(10)
    ex, _ = executor(routes(book=book_payload(asks=[(0.995, 100)])), price_cap=0.99)
    with pytest.raises(ExecutionRefused, match="above the limit"):
        await ex.execute(buy(10, limit_price=1.0))


@pytest.mark.parametrize(
    ("market", "book", "message"),
    [
        (gamma_market(closed=True), None, "not open"),
        (gamma_market(acceptingOrders=False), None, "not open"),
        (None, book_payload(asks=[]), "no asks"),
        (None, None, "below the minimum"),
    ],
)
async def test_buy_refusals(
    market: dict | None, book: dict | None, message: str
) -> None:
    ex, _ = executor(routes(market, book))
    with pytest.raises(ExecutionRefused, match=message):
        await ex.execute(buy(1.0 if message == "below the minimum" else 10))


async def test_buy_refused_below_min_notional() -> None:
    ex, _ = executor(
        routes(
            gamma_market(orderMinSize=0),
            book_payload(asks=[(0.05, 1000)], min_order_size="0"),
        ),
        min_notional=1.0,
    )
    with pytest.raises(ExecutionRefused, match=r"below \$1"):
        await ex.execute(buy(0.5))


async def test_unknown_token_and_lookup_failure() -> None:
    ex, _ = executor(FakeTransport({"/markets?": []}))
    with pytest.raises(ExecutionRefused, match="unknown token"):
        await ex.execute(buy())
    ex, _ = executor(FakeTransport({"/markets?": Response(500, b"")}))
    with pytest.raises(ExecutionRefused, match="market lookup failed"):
        await ex.execute(buy())


async def test_book_failures_refuse() -> None:
    ex, _ = executor(FakeTransport({"/markets?": [gamma_market()]}))
    with pytest.raises(ExecutionRefused, match="no order book"):
        await ex.execute(buy())
    ex, _ = executor(
        FakeTransport({"/markets?": [gamma_market()], "/book": Response(502, b"")})
    )
    with pytest.raises(ExecutionRefused, match="order book read failed"):
        await ex.execute(buy())


async def test_sell_walks_bids_and_reports_partial_fills() -> None:
    ex, _ = executor(routes())
    fill = await ex.execute(sell(60))
    assert fill.size == pytest.approx(60)
    assert fill.notional == pytest.approx(0.59 * 50 + 0.58 * 10)
    assert fill.costs.components["fee"] > 0
    assert fill.metadata["partial"] is False
    fill = await ex.execute(sell(500, limit_price=0.59))
    assert fill.size == pytest.approx(50) and fill.metadata["partial"] is True


async def test_sell_of_a_resolved_market_redeems_without_fee() -> None:
    won = gamma_market(prices=["0", "1"], closed=True)
    ex, transport = executor(routes(won))
    fill = await ex.execute(OrderRequest(instrument_id=NO, side=Side.SELL, size=12.345))
    assert fill.price == 1.0 and fill.size == 12.34 and fill.notional == 12.34
    assert fill.costs.components == {"fee": 0.0}
    assert str(fill.reference).startswith("paper-redeem-") and fill.metadata["redeemed"]
    assert transport.count("/book") == 0
    lost = await ex.execute(sell(5))
    assert lost.price == 0.0 and lost.notional == 0.0


@pytest.mark.parametrize(
    ("market", "book", "order", "message"),
    [
        (None, None, sell(0.001), "rounds to zero"),
        (gamma_market(closed=True), None, sell(), "not yet resolved"),
        (None, book_payload(bids=[]), sell(), "no bids"),
        (None, None, sell(10, limit_price=0.9), "no bids at or above"),
    ],
)
async def test_sell_refusals(
    market: dict | None, book: dict | None, order: OrderRequest, message: str
) -> None:
    ex, _ = executor(routes(market, book))
    with pytest.raises(ExecutionRefused, match=message):
        await ex.execute(order)


async def test_sell_always_rereads_the_market() -> None:
    ex, transport = executor(routes())
    await ex.execute(buy())
    await ex.execute(sell(5))
    assert transport.count("/markets?") == 2


async def test_live_executor_refuses() -> None:
    with pytest.raises(ExecutionRefused, match="not implemented"):
        await LiveExecutor().execute(buy())
