"""Assembles the enabled lanes into one trading-core pipeline.

trading-core runs one :class:`StrategyPipeline` per module. Each lane brings
its own scout and analyst; candidates carry their lane name, the shared
filters read that lane's thresholds, and :class:`LaneRouter` hands each
candidate to its lane's analyst. Every signal is tagged with the lane as its
``strategy``, so the audit tools can judge each lane on its own.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from trading_core.strategy.pipeline import (
    Analyst,
    Candidate,
    PipelineResult,
    Scout,
    Signal,
    StrategyPipeline,
)

from trading_polymarket.strategies.common import KEY_LANE
from trading_polymarket.strategies.filters import BookFilter, MarketStateFilter


class LaneRouter(Analyst):
    name = "lane-router"

    def __init__(self, analysts: Mapping[str, Analyst]) -> None:
        if not analysts:
            raise ValueError("LaneRouter needs at least one lane")
        self.analysts = dict(analysts)

    async def evaluate(
        self, candidate: Candidate, screening_metrics: Mapping[str, Any]
    ) -> Signal | None:
        lane = str(candidate.data.get(KEY_LANE))
        analyst = self.analysts.get(lane)
        if analyst is None:
            raise ValueError(f"no analyst for lane {lane!r}")
        return await analyst.evaluate(candidate, screening_metrics)


class LanePipeline(StrategyPipeline):
    """A pipeline that never buys the other side of a token already held.

    The engine excludes held tokens; holding "19°C Yes" and then buying
    "19°C No" pays two spreads for a position that cannot win (day 1 of the
    pilot did exactly that in Wellington, TP-8). ``complement_of`` names a
    token's other side when the market is known.
    """

    def __init__(
        self,
        *,
        complement_of: Callable[[str], str | None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.complement_of = complement_of

    async def run(self, *, exclude: Iterable[str] = ()) -> PipelineResult:
        held = set(exclude)
        if self.complement_of is not None:
            held |= {c for t in list(held) if (c := self.complement_of(t))}
        return await super().run(exclude=held)


def build_pipeline(
    lanes: Mapping[str, tuple[Scout, Analyst]],
    *,
    market_filter: MarketStateFilter,
    book_filter: BookFilter,
    max_candidates: int,
    complement_of: Callable[[str], str | None] | None = None,
) -> StrategyPipeline | None:
    """One pipeline over every lane in ``lanes``; ``None`` when there are none."""
    if not lanes:
        return None
    return LanePipeline(
        scouts=[scout for scout, _ in lanes.values()],
        filters=[market_filter, book_filter],
        analyst=LaneRouter({name: analyst for name, (_, analyst) in lanes.items()}),
        max_candidates=max_candidates,
        complement_of=complement_of,
    )


__all__ = ["LanePipeline", "LaneRouter", "build_pipeline"]
