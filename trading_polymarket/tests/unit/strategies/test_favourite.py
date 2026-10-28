from __future__ import annotations

from typing import Any

from trading_core.strategy.pipeline import Candidate

from trading_polymarket.calibration import CalibrationTable, Observation
from trading_polymarket.catalogue import BookCache, MarketCatalogue
from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.config import FavouriteLane
from trading_polymarket.strategies.common import KEY_FAIR, KEY_LANE, KEY_MARKET
from trading_polymarket.strategies.favourite import (
    FavouriteAnalyst,
    FavouriteScout,
    iso,
)
from trading_polymarket.tests.support.factories import (
    NO,
    NOW,
    YES,
    book_payload,
    gamma_market,
    market,
)
from trading_polymarket.tests.support.fakes import Clock, FakeTransport, fake_http

LANE = FavouriteLane(enabled=True, min_samples=50, min_edge=0.01)


def calibrated(price: float = 0.85, won: int = 98, n: int = 100) -> CalibrationTable:
    """Tokens near ``price`` closing in 6-24h won ``won`` of ``n`` times."""
    return CalibrationTable.build(
        [Observation(price, 10, i < won) for i in range(n)], prior_strength=10
    )


def favourite_market(**kw: Any) -> dict:
    base = {"bestBid": 0.84, "bestAsk": 0.85, "endDate": iso(NOW + 10 * 3600)}
    base.update(kw)
    return gamma_market(**base)


def scout(
    markets: list[dict], table: CalibrationTable, lane: FavouriteLane = LANE
) -> tuple[FavouriteScout, FakeTransport]:
    transport = FakeTransport({"/markets/keyset": {"markets": markets}})
    gamma = GammaClient(fake_http(transport))
    return (
        FavouriteScout(gamma, MarketCatalogue(gamma), table, lane, clock=Clock(NOW)),
        transport,
    )


def test_iso() -> None:
    assert iso(NOW) == "2026-10-28T12:00:00Z"


async def test_scout_finds_calibrated_favourites_in_the_window() -> None:
    s, transport = scout([favourite_market()], calibrated())
    found = await s.discover()
    assert [c.instrument_id for c in found] == [YES]
    assert found[0].data[KEY_LANE] == "favourite"
    assert found[0].data["calibration_n"] == 100
    assert found[0].data[KEY_FAIR] > 0.85
    url = transport.calls[0]
    assert "end_date_min=2026-10-28T13" in url and "order=volume24hr" in url


async def test_scout_finds_nothing_without_calibration_or_edge() -> None:
    s, _ = scout([favourite_market()], CalibrationTable())
    assert await s.discover() == []
    s, _ = scout([favourite_market()], calibrated(won=85))
    assert await s.discover() == []


async def test_scout_skips_excluded_shapes_and_prices() -> None:
    sports = {"tags": [{"slug": "sports"}]}
    lane = FavouriteLane(enabled=True, min_samples=50, exclude_tags=("sports",))
    s, _ = scout([favourite_market(events=[sports])], calibrated(), lane)
    assert await s.discover() == []
    s, _ = scout(
        [
            favourite_market(endDate=None),
            favourite_market(bestAsk=0.5, bestBid=0.49),
            favourite_market(bestAsk=None, bestBid=None),
            gamma_market(
                clobTokenIds='["a","b","c"]',
                outcomes='["A","B","C"]',
                outcomePrices='["0.1","0.1","0.8"]',
            ),
        ],
        calibrated(),
    )
    assert await s.discover() == []


async def test_scout_considers_the_no_side() -> None:
    s, _ = scout([favourite_market(bestBid=0.15, bestAsk=0.16)], calibrated())
    found = await s.discover()
    assert [c.instrument_id for c in found] == [NO]


def analyst(payload: dict, table: CalibrationTable) -> FavouriteAnalyst:
    books = BookCache(ClobClient(fake_http(FakeTransport({"/book": payload}))))
    return FavouriteAnalyst(books, table, LANE, bankroll=1000, clock=Clock(NOW))


def candidate() -> Candidate:
    m = market(endDate=iso(NOW + 10 * 3600))
    return Candidate(YES, name="fav", data={KEY_LANE: "favourite", KEY_MARKET: m})


async def test_analyst_signals_with_the_live_ask() -> None:
    payload = book_payload(asks=[(0.85, 500)])
    signal = await analyst(payload, calibrated()).evaluate(candidate(), {})
    assert signal is not None and signal.strategy == "favourite"
    assert signal.metrics["calibration_n"] == 100
    assert signal.limit_price == 0.85


async def test_analyst_declines() -> None:
    assert (
        await analyst(book_payload(asks=[]), calibrated()).evaluate(candidate(), {})
        is None
    )
    assert (
        await analyst(book_payload(asks=[(0.85, 500)]), CalibrationTable()).evaluate(
            candidate(), {}
        )
        is None
    )
    assert (
        await analyst(book_payload(asks=[(0.85, 500)]), calibrated(won=85)).evaluate(
            candidate(), {}
        )
        is None
    )
    no_end = Candidate(
        YES, data={KEY_LANE: "favourite", KEY_MARKET: market(endDate=None)}
    )
    assert (
        await analyst(book_payload(asks=[(0.85, 500)]), calibrated()).evaluate(
            no_end, {}
        )
        is None
    )
