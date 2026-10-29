from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from trading_core.strategy.pipeline import (
    Analyst,
    Candidate,
    Filter,
    Scout,
    Screening,
    Signal,
)

from trading_polymarket.catalogue import BookCache
from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.config import PolymarketSettings
from trading_polymarket.strategies.common import KEY_LANE
from trading_polymarket.strategies.filters import BookFilter, MarketStateFilter
from trading_polymarket.strategies.router import (
    LanePipeline,
    LaneRouter,
    build_pipeline,
)
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http


class Echo(Analyst):
    name = "echo"

    async def evaluate(
        self, candidate: Candidate, screening_metrics: Mapping[str, Any]
    ) -> Signal | None:
        return Signal(candidate.instrument_id, reason="echo", strategy="weather")


class Nothing(Scout):
    async def discover(self) -> Sequence[Candidate]:
        return []


async def test_router_dispatches_by_lane() -> None:
    router = LaneRouter({"weather": Echo()})
    signal = await router.evaluate(Candidate("t", data={KEY_LANE: "weather"}), {})
    assert signal is not None and signal.reason == "echo"
    with pytest.raises(ValueError):
        await router.evaluate(Candidate("t", data={KEY_LANE: "other"}), {})
    with pytest.raises(ValueError):
        LaneRouter({})


class Offer(Scout):
    name = "offer"

    async def discover(self) -> Sequence[Candidate]:
        return [Candidate(t, data={KEY_LANE: "weather"}) for t in ("yes", "no", "x")]


class Pass(Filter):
    async def screen(self, candidate: Candidate) -> Screening:
        return Screening.accept()


@pytest.mark.regression("TP-8")
async def test_pipeline_never_offers_the_other_side_of_a_held_token() -> None:
    pairs = {"yes": "no", "no": "yes"}
    pipeline = LanePipeline(
        scouts=[Offer()],
        analyst=Echo(),
        filters=[Pass()],
        complement_of=pairs.get,
    )
    result = await pipeline.run(exclude=["yes"])
    assert [s.instrument_id for s in result.signals] == ["x"]
    plain = LanePipeline(scouts=[Offer()], analyst=Echo())
    assert len((await plain.run(exclude=["yes"])).signals) == 2


def test_build_pipeline() -> None:
    settings = PolymarketSettings()
    books = BookCache(ClobClient(fake_http(FakeTransport())))
    filters: dict[str, Any] = {
        "market_filter": MarketStateFilter(settings),
        "book_filter": BookFilter(settings, books),
    }
    assert build_pipeline({}, max_candidates=5, **filters) is None
    pipeline = build_pipeline(
        {"weather": (Nothing(), Echo())}, max_candidates=5, **filters
    )
    assert pipeline is not None
    assert pipeline.describe() == "scout -> market-state -> order-book -> lane-router"
