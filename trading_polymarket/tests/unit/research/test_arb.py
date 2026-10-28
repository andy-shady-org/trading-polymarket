from __future__ import annotations

from typing import Any

import pytest

from trading_polymarket.book import OrderBook
from trading_polymarket.catalogue import BookCache
from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.research.arb import (
    KIND_PAIR,
    KIND_SET,
    ArbScanner,
    _evaluate,
    _leg_cost,
)
from trading_polymarket.tests.support.factories import (
    NOW,
    book_payload,
    gamma_market,
    market,
)
from trading_polymarket.tests.support.fakes import Clock, FakeTransport, fake_http


def test_leg_cost_includes_the_fee() -> None:
    m = market()
    b = OrderBook.from_levels("t", [], [(0.5, 10)])
    assert _leg_cost(b, m) == (pytest.approx(0.5 + 0.05 * 0.25), 10)
    assert _leg_cost(OrderBook.from_levels("t", [], []), m) is None


def test_evaluate_thresholds() -> None:
    free = market(feeSchedule=None, feesEnabled=False)
    cheap = OrderBook.from_levels("t", [], [(0.45, 100)])
    legs = [(cheap, free), (cheap, free)]
    opp = _evaluate(
        KIND_PAIR, "q", legs, augmented=False, min_profit=0.05, min_size=5, now=NOW
    )
    assert opp is not None and opp.profit == pytest.approx(0.1) and opp.size == 100
    assert opp.to_dict()["kind"] == KIND_PAIR
    assert (
        _evaluate(
            KIND_PAIR, "q", legs, augmented=False, min_profit=0.2, min_size=5, now=NOW
        )
        is None
    )
    assert (
        _evaluate(
            KIND_PAIR, "q", legs, augmented=False, min_profit=0.0, min_size=500, now=NOW
        )
        is None
    )
    empty = OrderBook.from_levels("t", [], [])
    assert (
        _evaluate(
            KIND_PAIR,
            "q",
            [(empty, free)],
            augmented=False,
            min_profit=0,
            min_size=0,
            now=NOW,
        )
        is None
    )
    assert (
        _evaluate(
            KIND_PAIR, "q", [], augmented=False, min_profit=0, min_size=0, now=NOW
        )
        is None
    )


def scanner(events: list[dict], books: dict[str, dict]) -> ArbScanner:
    routes: dict[str, object] = {"/events/keyset": {"events": events}}
    for token, payload in books.items():
        routes[f"token_id={token}"] = payload
    http = fake_http(FakeTransport(routes), max_retries=0)
    return ArbScanner(
        GammaClient(http),
        BookCache(ClobClient(http)),
        min_profit=0.01,
        clock=Clock(NOW),
    )


def leg(token: str, ask: float) -> dict:
    return book_payload(token, bids=[(ask - 0.02, 50)], asks=[(ask, 50)])


async def test_scan_finds_a_neg_risk_set_and_a_binary_pair() -> None:
    a = gamma_market(
        id="1",
        yes="a" * 20,
        no="b" * 20,
        negRisk=True,
        bestAsk=0.30,
        bestBid=0.29,
        feeSchedule=None,
        feesEnabled=False,
    )
    c = gamma_market(
        id="2",
        yes="c" * 20,
        no="d" * 20,
        negRisk=True,
        bestAsk=0.40,
        bestBid=0.39,
        feeSchedule=None,
        feesEnabled=False,
    )
    pair = gamma_market(
        id="3",
        yes="e" * 20,
        no="f" * 20,
        bestAsk=0.48,
        bestBid=0.53,
        feeSchedule=None,
        feesEnabled=False,
    )
    events: list[dict[str, Any]] = [
        {"id": "x", "title": "Who wins?", "negRiskAugmented": True, "markets": [a, c]},
        {"id": "y", "title": "Pair", "markets": [pair]},
    ]
    books = {
        "a" * 20: leg("a", 0.30),
        "c" * 20: leg("c", 0.40),
        "b" * 20: leg("b", 0.75),
        "d" * 20: leg("d", 0.65),
        "e" * 20: leg("e", 0.48),
        "f" * 20: leg("f", 0.47),
    }
    found = await scanner(events, books).scan()
    kinds = {o.kind: o for o in found}
    assert kinds[KIND_SET].augmented and kinds[KIND_SET].cost == pytest.approx(0.70)
    assert kinds[KIND_PAIR].profit == pytest.approx(0.05)
    assert found[0].profit >= found[-1].profit


async def test_scan_skips_quotes_far_from_arbitrage_and_missing_books() -> None:
    wide = gamma_market(id="1", yes="a" * 20, no="b" * 20, bestAsk=0.60, bestBid=0.40)
    blank = gamma_market(id="2", yes="c" * 20, no="d" * 20, bestAsk=None, bestBid=None)
    near = gamma_market(id="3", yes="e" * 20, no="f" * 20, bestAsk=0.50, bestBid=0.50)
    neg = [
        gamma_market(
            id=str(i),
            yes=f"{i}" * 20,
            no=f"9{i}" * 10,
            negRisk=True,
            bestAsk=0.6,
            bestBid=0.5,
        )
        for i in range(1, 3)
    ]
    neg_missing = [
        gamma_market(
            id=str(i),
            yes=f"{i}" * 21,
            no=f"8{i}" * 10,
            negRisk=True,
            bestAsk=0.3,
            bestBid=0.2,
        )
        for i in range(5, 7)
    ]
    neg_noask = [
        gamma_market(
            id="7", yes="7" * 20, no="87" * 10, negRisk=True, bestAsk=None, bestBid=0.2
        ),
        gamma_market(
            id="8", yes="8" * 20, no="88" * 10, negRisk=True, bestAsk=0.3, bestBid=0.2
        ),
    ]
    events = [
        {"title": "a", "markets": [wide, blank, near]},
        {"title": "b", "markets": neg},
        {"title": "c", "markets": neg_missing},
        {"title": "d", "markets": neg_noask},
    ]
    assert await scanner(events, {}).scan() == []
    books = {f"{i}" * 21: leg("x", 0.3) for i in range(5, 7)}
    books |= {"e" * 20: leg("e", 0.6), "f" * 20: leg("f", 0.6)}
    found = await scanner(events, books).scan()
    assert [(o.kind, o.title) for o in found] == [(KIND_SET, "c")]
    dear = {f"{i}" * 21: leg("x", 0.6) for i in range(5, 7)}
    assert await scanner(events, dear).scan() == []
