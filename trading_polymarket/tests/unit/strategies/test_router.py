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
    STAGE_DAY_CAP,
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


class Many(Scout):
    """Five weather and two fed candidates."""

    async def discover(self) -> Sequence[Candidate]:
        weather = [Candidate(f"w{i}", data={KEY_LANE: "weather"}) for i in range(5)]
        fed = [Candidate(f"f{i}", data={KEY_LANE: "fed"}) for i in range(2)]
        return weather + fed


class ByLane(Analyst):
    name = "by-lane"

    async def evaluate(
        self, candidate: Candidate, screening_metrics: Mapping[str, Any]
    ) -> Signal | None:
        lane = str(candidate.data[KEY_LANE])
        return Signal(candidate.instrument_id, reason=lane, strategy=lane)


@pytest.mark.regression("TP-12")
async def test_a_lane_holds_at_most_its_cap_on_one_day() -> None:
    # Day 1 of the 0.2.0 weather pilot: ten bets on one day's late-day
    # thesis, each Kelly-sized as if independent; all ten lost.
    days = {"w0": "D1", "w1": "D1", "w2": "D1", "w3": "D2", "w4": "D1"}
    pipeline = LanePipeline(
        scouts=[Many()],
        analyst=ByLane(),
        day_of=days.get,
        day_caps={"weather": 2, "fed": 0},
    )
    first = await pipeline.run()
    kept = [s.instrument_id for s in first.signals]
    assert kept == ["w0", "w1", "w3", "f0", "f1"]  # fed: no cap
    capped = [r for r in first.rejections if r.stage == STAGE_DAY_CAP]
    assert [r.instrument_id for r in capped] == ["w2", "w4"]
    assert capped[0].reason == "weather already holds 2 closing D1"
    # Next cycle, holding w0 and w1: D1 stays full, D2 has room.
    again = await pipeline.run(exclude=["w0", "w1"])
    assert [s.instrument_id for s in again.signals] == ["w3", "f0", "f1"]
    # After a restart the module does not know who bought what: an unknown
    # token counts against every lane, an unknown day against every day.
    restarted = LanePipeline(
        scouts=[Many()],
        analyst=ByLane(),
        day_of=lambda t: None if t == "old" else days.get(t),
        day_caps={"weather": 1},
    )
    after = await restarted.run(exclude=["old"])
    assert [s.instrument_id for s in after.signals] == ["f0", "f1"]


async def test_without_caps_every_signal_passes() -> None:
    pipeline = LanePipeline(scouts=[Many()], analyst=ByLane(), day_caps={"weather": 0})
    assert len((await pipeline.run(exclude=["w0"])).signals) == 6


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
