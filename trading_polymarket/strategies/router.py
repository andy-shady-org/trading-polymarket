"""Assembles the enabled lanes into one trading-core pipeline.

trading-core runs one :class:`StrategyPipeline` per module. Each lane brings
its own scout and analyst; candidates carry their lane name, the shared
filters read that lane's thresholds, and :class:`LaneRouter` hands each
candidate to its lane's analyst. Every signal is tagged with the lane as its
``strategy``, so the audit tools can judge each lane on its own.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from trading_core.strategy.pipeline import (
    Analyst,
    Candidate,
    PipelineResult,
    Rejection,
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


STAGE_DAY_CAP = "lane-day-cap"


class LanePipeline(StrategyPipeline):
    """A pipeline that never buys the other side of a token already held, and
    never holds more than a lane's ``max_positions_per_day`` on one day.

    The engine excludes held tokens; holding "19°C Yes" and then buying
    "19°C No" pays two spreads for a position that cannot win (day 1 of the
    pilot did exactly that in Wellington, TP-8). ``complement_of`` names a
    token's other side when the market is known.

    Bets settled on one day share its weather (or meeting, or thesis), yet
    Kelly sizes each as if independent: day 1 of the 0.2.0 weather pilot
    bought ten bets on one late-day thesis and lost all ten (TP-12).
    ``day_of`` names the UTC date a token's market closes; ``day_caps`` the
    cap per lane. Held tokens count in the lane that bought them; one whose
    lane or day is unknown (after a restart) counts against every lane or
    day, which can only make the cap stricter.
    """

    def __init__(
        self,
        *,
        complement_of: Callable[[str], str | None] | None = None,
        day_of: Callable[[str], str | None] | None = None,
        day_caps: Mapping[str, int] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.complement_of = complement_of
        self.day_of = day_of or (lambda _token: None)
        self.day_caps = {lane: cap for lane, cap in (day_caps or {}).items() if cap}
        self.lane_of: dict[str, str] = {}  # token -> lane of the signal that bought it

    async def run(self, *, exclude: Iterable[str] = ()) -> PipelineResult:
        held = set(exclude)
        blocked = set(held)
        if self.complement_of is not None:
            blocked |= {c for t in held if (c := self.complement_of(t))}
        result = await super().run(exclude=blocked)
        result.signals = self._capped(result, held)
        for signal in result.signals:
            self.lane_of[signal.instrument_id] = str(signal.strategy)
        return result

    def _capped(self, result: PipelineResult, held: set[str]) -> list[Signal]:
        if not self.day_caps:
            return result.signals
        counts: Counter[tuple[str | None, str | None]] = Counter(
            (self.lane_of.get(token), self.day_of(token)) for token in held
        )
        kept: list[Signal] = []
        for signal in result.signals:  # best first
            lane, day = str(signal.strategy), self.day_of(signal.instrument_id)
            cap = self.day_caps.get(lane)
            if cap is not None and _open(counts, lane, day) >= cap:
                result.rejections.append(
                    Rejection(
                        signal.instrument_id,
                        STAGE_DAY_CAP,
                        f"{lane} already holds {cap} closing {day}",
                        signal.name,
                    )
                )
                continue
            counts[lane, day] += 1
            kept.append(signal)
        return kept


def _open(
    counts: Counter[tuple[str | None, str | None]], lane: str, day: str | None
) -> int:
    """Held in ``lane`` on ``day``, counting unknown lanes and days as matches."""
    return sum(
        n
        for (held_lane, held_day), n in counts.items()
        if held_lane in (lane, None) and (held_day == day or held_day is None)
    )


def build_pipeline(
    lanes: Mapping[str, tuple[Scout, Analyst]],
    *,
    market_filter: MarketStateFilter,
    book_filter: BookFilter,
    max_candidates: int,
    complement_of: Callable[[str], str | None] | None = None,
    day_of: Callable[[str], str | None] | None = None,
    day_caps: Mapping[str, int] | None = None,
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
        day_of=day_of,
        day_caps=day_caps,
    )


__all__ = ["STAGE_DAY_CAP", "LanePipeline", "LaneRouter", "build_pipeline"]
