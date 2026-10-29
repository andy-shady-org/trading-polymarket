from __future__ import annotations

from typing import Any

import pytest
from trading_core.strategy.pipeline import Candidate

from trading_polymarket.catalogue import BookCache, MarketCatalogue
from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.kalshi import KalshiClient, KalshiMarket
from trading_polymarket.config import CrossVenueLane, FedLane, ReferenceLane
from trading_polymarket.pairs import SIDE_NO, SIDE_YES, Reference, VenuePair, save_pairs
from trading_polymarket.strategies.common import KEY_FAIR, KEY_LANE, KEY_MARKET
from trading_polymarket.strategies.crossvenue import (
    KEY_PAIR,
    ApprovedPairs,
    FedPairs,
    Listing,
    PairSource,
    ReferenceAnalyst,
    ReferenceBook,
    ReferenceScout,
    converged,
    reference_fair,
    usable,
)
from trading_polymarket.tests.support.factories import (
    NOW,
    YES,
    book_payload,
    fed_kalshi_event,
    fed_no,
    fed_pm_event,
    fed_yes,
    gamma_market,
    iso,
    kalshi_market,
    market,
)
from trading_polymarket.tests.support.fakes import Clock, FakeTransport, fake_http

LANE = FedLane(enabled=True)
TICKER = "KXFEDDECISION-26NOV-H0"


def ref(bid: float | None = 0.60, ask: float | None = 0.62, **kw: Any) -> Reference:
    return Reference(bid, ask, kw.get("volume", 25000.0), kw.get("t", NOW))


def kalshi(transport: FakeTransport) -> KalshiClient:
    return KalshiClient(fake_http(transport, max_retries=0), base_url="https://k.test")


def test_reference_fair_and_usable() -> None:
    assert reference_fair(ref(), LANE) == pytest.approx(0.61)
    assert reference_fair(ref(), FedLane(reference="bid")) == 0.60
    assert usable(ref(), LANE, NOW) is None
    assert "two-sided" in str(usable(ref(bid=None), LANE, NOW))
    assert "spread" in str(usable(ref(0.5, 0.6), LANE, NOW))
    assert "thin" in str(usable(ref(volume=10), LANE, NOW))
    assert "old" in str(usable(ref(t=NOW - 601), LANE, NOW))


def test_converged() -> None:
    assert converged(ref(), 0.61, LANE, NOW)
    assert not converged(ref(), 0.60, LANE, NOW)
    assert converged(ref(), 0.60, FedLane(convergence_margin=0.01), NOW)
    assert not converged(None, 0.9, LANE, NOW)
    assert not converged(ref(), None, LANE, NOW)
    assert not converged(ref(), 0.9, FedLane(exit_on_convergence=False), NOW)
    assert not converged(ref(t=NOW - 601), 0.9, LANE, NOW)
    assert not converged(ref(bid=None), 0.9, LANE, NOW)


async def test_reference_book_caches_markets_and_events() -> None:
    transport = FakeTransport(
        {
            "/markets/": {"market": kalshi_market()},
            "/events?": {"events": [fed_kalshi_event()]},
        }
    )
    clock = Clock(NOW)
    book = ReferenceBook(kalshi(transport), ttl=60, clock=clock)
    assert book.latest(YES) is None
    book.remember(YES, ref())
    assert book.latest(YES) == ref()
    first = await book.market(TICKER)
    assert await book.market(TICKER) is first
    assert len(await book.series_events("KXFEDDECISION")) == 1
    await book.series_events("KXFEDDECISION")
    assert transport.count("/markets/") == 1 and transport.count("/events?") == 1
    clock.advance(61)
    await book.market(TICKER)
    await book.series_events("KXFEDDECISION")
    assert transport.count("/markets/") == 2 and transport.count("/events?") == 2


def fed_source(
    pm_events: list[dict], kalshi_events: list[dict]
) -> tuple[FedPairs, MarketCatalogue, ReferenceBook]:
    transport = FakeTransport(
        {
            "/public-search": {"events": pm_events},
            "/events?": {"events": kalshi_events},
        }
    )
    http = fake_http(transport, max_retries=0)
    gamma = GammaClient(http)
    catalogue = MarketCatalogue(gamma, clock=Clock(NOW))
    references = ReferenceBook(KalshiClient(http), clock=Clock(NOW))
    return FedPairs(gamma, catalogue, references), catalogue, references


async def test_fed_pairs_lists_matched_buckets_and_caches_their_markets() -> None:
    source, catalogue, _ = fed_source([fed_pm_event()], [fed_kalshi_event()])
    listings = await source.listings()
    assert len(listings) == 10
    pair, pm_market, k_market = next(
        item for item in listings if item[0].pm_token == fed_yes("No change")
    )
    assert pair.kalshi_ticker == TICKER and k_market.ticker == TICKER
    assert pm_market.group_item_title == "No change"
    assert catalogue.cached(fed_no("No change")) is pm_market


class Fixed(PairSource):
    def __init__(self, listings: list[Listing]) -> None:
        self.items = listings

    async def listings(self) -> list[Listing]:
        return self.items


def listing(
    bucket_ask: float = 0.55,
    side: str = SIDE_YES,
    kalshi_quote: tuple[str, str] = ("0.6000", "0.6200"),
    **pm: Any,
) -> Listing:
    token = YES if side == SIDE_YES else "2" * 40
    base = {
        "bestAsk": bucket_ask,
        "bestBid": bucket_ask - 0.01,
        "feesEnabled": False,
        "feeSchedule": None,
    }
    if side == SIDE_NO:  # the No token's ask is 1 - bestBid
        base = {
            "bestBid": round(1 - bucket_ask, 4),
            "bestAsk": 1.0,
            "feesEnabled": False,
        }
    base.update(pm)
    k = KalshiMarket.from_api(
        kalshi_market(yes_bid_dollars=kalshi_quote[0], yes_ask_dollars=kalshi_quote[1])
    )
    return (
        VenuePair(token, TICKER, side, label="Fed Nov No change"),
        market(**base),
        k,
    )


def scout(
    items: list[Listing], lane: FedLane = LANE
) -> tuple[ReferenceScout, ReferenceBook]:
    references = ReferenceBook(kalshi(FakeTransport()), clock=Clock(NOW))
    return (
        ReferenceScout(
            "fed-vs-kalshi", "fed", Fixed(items), references, lane, clock=Clock(NOW)
        ),
        references,
    )


async def test_scout_ranks_tokens_below_the_reference() -> None:
    small = listing(0.59)
    big = listing(0.55)
    big = (
        VenuePair("3" * 40, TICKER),
        market(bestAsk=0.55, yes="3" * 40, feesEnabled=False, feeSchedule=None),
        big[2],
    )
    s, references = scout([small, big])
    found = await s.discover()
    assert [c.instrument_id for c in found] == ["3" * 40, YES]
    top = found[0]
    assert top.source == "fed-vs-kalshi" and top.name  # no label: the market's
    assert top.data[KEY_LANE] == "fed" and top.data["gamma_ask"] == 0.55
    assert top.data[KEY_PAIR].kalshi_ticker == TICKER
    assert found[1].name == "Fed Nov No change"
    assert s.last_pairs == 2
    assert references.latest(YES) is not None


async def test_scout_reads_the_no_side_as_one_minus_yes() -> None:
    # Kalshi Yes 0.60/0.62 -> No 0.38/0.40; Polymarket No ask 0.30 is cheap.
    s, references = scout([listing(0.30, side=SIDE_NO)])
    found = await s.discover()
    assert len(found) == 1
    assert references.latest("2" * 40) == Reference(0.38, 0.40, 25000.0, NOW)


@pytest.mark.parametrize(
    ("item", "lane"),
    [
        (listing(0.55, acceptingOrders=False), LANE),  # not tradable
        (listing(0.55, endDate=iso(NOW + 1800)), LANE),  # closes within min_hours
        (listing(0.55, kalshi_quote=("0.50", "0.60")), LANE),  # wide reference
        (listing(0.55, bestAsk=None), LANE),  # no Gamma ask
        (listing(0.02, kalshi_quote=("0.0300", "0.0400")), LANE),  # below min_price
        (listing(0.605), LANE),  # gap below min_edge / 2
        (listing(0.40), LANE),  # gap above max_edge
    ],
)
async def test_scout_skips(item: Listing, lane: FedLane) -> None:
    s, references = scout([item], lane)
    assert await s.discover() == []
    assert references.latest(item[0].pm_token) is not None  # still remembered


async def test_scout_bid_reference_and_candidate_cap() -> None:
    s, _ = scout([listing(0.55)], FedLane(reference="bid", min_reference_volume=0))
    assert len(await s.discover()) == 1
    capped, _ = scout([listing(0.55), listing(0.56)], FedLane(max_candidates=1))
    assert len(await capped.discover()) == 1


async def test_approved_pairs_reload_and_skip_unreadable(
    tmp_path,
) -> None:  # noqa: ANN001
    path = tmp_path / "pairs.json"
    transport = FakeTransport(
        {
            "/markets?": [gamma_market()],
            "/markets/GOOD": {"market": kalshi_market("GOOD")},
        }
    )
    http = fake_http(transport, max_retries=0)
    gamma = GammaClient(http)
    catalogue = MarketCatalogue(gamma, clock=Clock(NOW))
    references = ReferenceBook(KalshiClient(http), clock=Clock(NOW))
    source = ApprovedPairs(str(path), catalogue, references)
    assert await source.listings() == []
    save_pairs(
        [VenuePair(YES, "GOOD"), VenuePair(YES, "BAD"), VenuePair("9" * 40, "GOOD")],
        path,
    )
    first = source.pairs()
    assert source.pairs() is first  # unchanged file: not reloaded
    listings = await source.listings()
    assert [(p.pm_token, k.ticker) for p, _, k in listings] == [(YES, "GOOD")]
    assert transport.count("/markets?") == 1  # one batched Gamma lookup


def analyst(
    transport: FakeTransport, lane: ReferenceLane = LANE, clock: Clock | None = None
) -> tuple[ReferenceAnalyst, ReferenceBook]:
    clob = ClobClient(fake_http(transport, max_retries=0))
    references = ReferenceBook(kalshi(FakeTransport()), clock=Clock(NOW))
    return (
        ReferenceAnalyst(
            "fed-kalshi-analyst",
            "fed",
            BookCache(clob),
            references,
            lane,
            bankroll=1000.0,
            clock=clock or Clock(NOW),
        ),
        references,
    )


def candidate(**data: Any) -> Candidate:
    payload = {
        KEY_LANE: "fed",
        KEY_MARKET: market(feesEnabled=False, feeSchedule=None),
        "kalshi_ticker": TICKER,
        "kalshi_side": SIDE_YES,
        "gamma_ask": 0.55,
    }
    payload.update(data)
    return Candidate(
        instrument_id=YES, name="Fed", source="fed-vs-kalshi", data=payload
    )


async def test_analyst_prices_against_the_reference_and_the_live_book() -> None:
    a, references = analyst(
        FakeTransport(
            {"/book": book_payload(asks=[(0.56, 200), (0.58, 500), (0.60, 900)])}
        )
    )
    references.remember(YES, ref())
    signal = await a.evaluate(candidate(), {})
    assert signal is not None
    assert signal.strategy == "fed" and signal.limit_price == 0.58
    assert signal.metrics[KEY_FAIR] == pytest.approx(0.61)
    assert (
        signal.metrics["kalshi_bid"] == 0.6 and signal.metrics["kalshi_spread"] == 0.02
    )
    assert "Kalshi 0.610" in signal.reason and 0 < signal.confidence <= 1


@pytest.mark.parametrize(
    ("reference", "asks"),
    [
        (None, [(0.56, 200)]),  # nothing remembered
        (ref(bid=None), [(0.56, 200)]),  # unusable
        (ref(), []),  # no ask
        (ref(), [(0.02, 200)]),  # below the band
        (ref(), [(0.40, 200)]),  # gap above max_edge
        (ref(), [(0.60, 200)]),  # no level with min_edge
    ],
)
async def test_analyst_rejects(reference: Reference | None, asks: list) -> None:
    a, references = analyst(FakeTransport({"/book": book_payload(asks=asks)}))
    if reference is not None:
        references.remember(YES, reference)
    assert await a.evaluate(candidate(), {}) is None


async def test_crossvenue_lane_uses_the_same_analyst() -> None:
    a, references = analyst(
        FakeTransport({"/book": book_payload(asks=[(0.56, 200)])}),
        lane=CrossVenueLane(enabled=True, reference="bid"),
    )
    references.remember(YES, ref())
    signal = await a.evaluate(candidate(), {})
    assert signal is not None and signal.metrics[KEY_FAIR] == 0.6
