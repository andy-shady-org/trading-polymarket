"""Collect resolved temperature events and replay the weather lane on them.

Collection (``trading-polymarket weather-history``) stores, per resolved
METAR-settled event: the station, local date, unit, every bucket with its
outcome and the Yes token's hourly price series. Open-Meteo's previous-runs
API then supplies, per station, the **day-ahead** model maxima (what was
forecast the day before), so the replay never sees the future.

Replay (``trading-polymarket backtest weather``): at local midnight of the
event day (``entry_hour`` later if set) the lane prices every bucket with the
same distribution and blending as live trading - day-ahead multi-model mean
plus a *rolling* station bias learnt only from earlier events - and buys
each token whose blended fair value beats the price plus a modelled
half-spread by ``min_edge``, holding to resolution.

``--intraday`` adds the observations: METARs (the last ~15 days only) give
the maximum observed before ``entry_hour`` as the distribution's floor, and
the day-ahead forecast of the remaining hours, moved by the share
``today_error_weight`` of the error it already made that day, gives its mean
with ``intraday_sigma`` - the live lane's model, replayed without hindsight.
Every replay also reports Brier scores of the model, the market and the
blend over every bucket it priced: a model that does not beat the market's
Brier score has no business trading against it.
"""

from __future__ import annotations

import asyncio
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.weather import Metar, PreviousRuns, WeatherClient
from trading_polymarket.config import LANE_WEATHER, WeatherLane
from trading_polymarket.fees import FeeSchedule
from trading_polymarket.research.backtest import BacktestResult, brier_scores
from trading_polymarket.research.records import append_jsonl, read_jsonl, round_trip
from trading_polymarket.strategies.common import kelly_fraction, net_edge
from trading_polymarket.strategies.weather import (
    MIN_BIAS_DAYS,
    WEATHER_TAG,
    TempDistribution,
    WeatherEvent,
    applied_bias,
    blend,
    intraday_mean,
    lead_sigma,
    station_zone,
    to_celsius,
)

DEFAULT_WEATHER_HISTORY = "data/history/weather.jsonl"


@dataclass(frozen=True)
class BucketHistory:
    low: int | None
    high: int | None
    yes_token: str
    no_token: str
    won: bool
    history: tuple[tuple[float, float], ...]
    fee_rate: float = 0.0

    def label(self, unit: str) -> str:
        if self.low is None:
            return f"<={self.high}°{unit}"
        if self.high is None:
            return f">={self.low}°{unit}"
        if self.low == self.high:
            return f"{self.low}°{unit}"
        return f"{self.low}-{self.high}°{unit}"

    def price_at(self, moment: float) -> float | None:
        price = None
        for t, p in self.history:
            if t > moment:
                break
            price = p
        return price


@dataclass(frozen=True)
class EventHistory:
    event_id: str
    city: str
    icao: str
    unit: str
    day: date
    end_time: float
    buckets: tuple[BucketHistory, ...] = field(default=())

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> EventHistory:
        return cls(
            event_id=str(row["event_id"]),
            city=str(row["city"]),
            icao=str(row["icao"]),
            unit=str(row["unit"]),
            day=date.fromisoformat(str(row["day"])),
            end_time=float(row["end_time"]),
            buckets=tuple(
                BucketHistory(
                    low=b.get("low"),
                    high=b.get("high"),
                    yes_token=str(b["yes_token"]),
                    no_token=str(b["no_token"]),
                    won=bool(b["won"]),
                    history=tuple((float(t), float(p)) for t, p in b["history"]),
                    fee_rate=float(b.get("fee_rate") or 0.0),
                )
                for b in row["buckets"]
            ),
        )

    def settled_celsius(self) -> float | None:
        """Middle of the winning bucket in °C (``None`` if open-ended)."""
        winner = next((b for b in self.buckets if b.won), None)
        if winner is None or winner.low is None or winner.high is None:
            return None
        return to_celsius((winner.low + winner.high) / 2.0, self.unit)


def load_events(path: str | Path = DEFAULT_WEATHER_HISTORY) -> list[EventHistory]:
    events = []
    for raw in read_jsonl(path):
        try:
            events.append(EventHistory.from_dict(raw))
        except (KeyError, TypeError, ValueError):
            continue
    events.sort(key=lambda e: (e.day, e.icao))
    return events


async def collect_weather(
    gamma: GammaClient,
    clob: ClobClient,
    *,
    start: date,
    end: date,
    path: str | Path = DEFAULT_WEATHER_HISTORY,
    cities: Sequence[str] = (),
    max_pages: int = 30,
    concurrency: int = 8,
    batch: int = 10,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Append resolved METAR-settled temperature events closing in the window.

    Events are fetched ``batch`` at a time (at most ``concurrency`` requests in
    flight). An event whose buckets have no price history at all is not
    stored, so a later run can collect it (TP-4).
    """
    seen = {str(r.get("event_id")) for r in read_jsonl(path)}
    pairs = await gamma.events(
        max_pages=max_pages,
        closed=True,
        tag_slug=WEATHER_TAG,
        end_date_min=f"{start.isoformat()}T00:00:00Z",
        end_date_max=f"{end.isoformat()}T23:59:59Z",
    )
    gate = asyncio.Semaphore(concurrency)
    todo = _todo(pairs, seen, {c.lower() for c in cities})
    written = 0
    for index in range(0, len(todo), batch):
        rows = await asyncio.gather(
            *(
                _fetch_event(clob, gate, e, progress)
                for e in todo[index : index + batch]
            )
        )
        written += append_jsonl(path, (r for r in rows if r is not None))
        if progress is not None:
            done = min(index + batch, len(todo))
            progress(f"{done}/{len(todo)} events: {written} collected")
    return written


def _todo(
    pairs: Sequence[tuple[Mapping[str, Any], Sequence[Any]]],
    seen: set[str],
    wanted: set[str],
) -> list[WeatherEvent]:
    """Resolved METAR events not collected yet (``seen`` grows)."""
    todo: list[WeatherEvent] = []
    for raw, markets in pairs:
        event = WeatherEvent.parse(raw, markets, legacy=True)
        if event is None or event.event_id in seen:
            continue
        if wanted and event.city.lower() not in wanted:
            continue
        if all(b.market.resolved for b in event.buckets):
            seen.add(event.event_id)
            todo.append(event)
    return todo


async def _series(
    clob: ClobClient, gate: asyncio.Semaphore, token: str, end_time: float
) -> list[list[float]]:
    async with gate:
        points = await clob.prices_history(
            token, start=end_time - 4 * 86400.0, end=end_time + 86400.0
        )
    return [[round(p.t), round(p.p, 5)] for p in points]


async def _fetch_event(
    clob: ClobClient,
    gate: asyncio.Semaphore,
    event: WeatherEvent,
    progress: Callable[[str], None] | None,
) -> dict[str, Any] | None:
    try:
        histories = await asyncio.gather(
            *(
                _series(clob, gate, b.market.yes_token, b.market.end_time or 0.0)
                for b in event.buckets
            )
        )
    except Exception as exc:  # skip this event, keep collecting
        if progress is not None:
            progress(f"{event.title}: {exc}")
        return None
    if not any(histories):  # TP-4: nothing to replay; retry next run
        if progress is not None:
            progress(f"{event.title}: no price history")
        return None
    return _event_row(event, histories)


def _event_row(
    event: WeatherEvent, histories: Sequence[list[list[float]]]
) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "title": event.title,
        "city": event.city,
        "icao": event.icao,
        "unit": event.unit,
        "day": event.day.isoformat(),
        "end_time": max(b.market.end_time or 0.0 for b in event.buckets),
        "buckets": [
            {
                "low": b.low,
                "high": b.high,
                "yes_token": b.market.yes_token,
                "no_token": b.market.no_token,
                "won": b.market.payout(b.market.yes_token) == 1.0,
                "fee_rate": b.market.fee.rate,
                "history": h,
            }
            for b, h in zip(event.buckets, histories, strict=True)
        ],
    }


async def station_metars(
    client: WeatherClient,
    icaos: Sequence[str],
    *,
    hours: int = 360,
    progress: Callable[[str], None] | None = None,
) -> dict[str, list[Metar]]:
    """Recent METARs per station (AWC keeps about 15 days)."""
    found: dict[str, list[Metar]] = {}
    for icao in sorted(set(icaos)):
        try:
            found[icao] = await client.metars(icao, hours=hours)
        except Exception as exc:  # one station must not sink the backtest
            if progress is not None:
                progress(f"{icao}: no METARs ({exc})")
    return found


async def day_ahead_forecasts(
    client: WeatherClient,
    stations: Mapping[str, Mapping[str, Any]],
    icaos: Sequence[str],
    *,
    models: Sequence[str],
    past_days: int,
    progress: Callable[[str], None] | None = None,
) -> dict[str, PreviousRuns]:
    """Day-ahead runs per station; a station that fails is reported and skipped."""
    found: dict[str, PreviousRuns] = {}
    for icao in sorted(set(icaos)):
        station = stations.get(icao)
        if station is None:
            continue
        try:
            found[icao] = await client.previous_day_maxima(
                float(station["lat"]),
                float(station["lon"]),
                models=models,
                past_days=past_days,
            )
        except Exception as exc:  # one station must not sink the backtest
            if progress is not None:
                progress(f"{icao}: no day-ahead forecasts ({exc})")
    return found


@dataclass
class _StationErrors:
    errors: list[float] = field(default_factory=list)

    def bias(self, minimum: int = 5) -> float:
        return statistics.fmean(self.errors) if len(self.errors) >= minimum else 0.0

    def sd(self, minimum: int = MIN_BIAS_DAYS) -> float | None:
        if len(self.errors) < minimum:
            return None
        return statistics.stdev(self.errors)


def _observed_max(
    metars: Sequence[Metar], day: date, zone: tzinfo, before: float
) -> tuple[bool, float | None]:
    """``(covered, max)``: whether METARs exist for the local day at all, and
    the highest routine temperature observed on it before ``before``."""
    covered = False
    best: float | None = None
    for metar in metars:
        if datetime.fromtimestamp(metar.obs_time, zone).date() != day:
            continue
        covered = True
        if metar.routine and metar.temperature is not None and metar.obs_time < before:
            best = metar.temperature if best is None else max(best, metar.temperature)
    return covered, best


def _forecast_only(
    values: Sequence[float],
    bias: float,
    lane: WeatherLane,
    entry_hour: int,
    history: _StationErrors,
) -> TempDistribution:
    """Forecast plus bias, σ from the lead-time curve (no observation yet)."""
    lead_hours = max(0.0, float(lane.peak_hour - entry_hour))
    spread = statistics.pstdev(values) if len(values) > 1 else 0.0
    sigma = lead_sigma(lane, lead_hours, spread=spread, measured_sd=history.sd())
    return TempDistribution(mu=statistics.fmean(values) + bias, sigma=sigma)


def _distribution(
    event: EventHistory,
    runs: PreviousRuns,
    lane: WeatherLane,
    entry_hour: int,
    observations: Mapping[str, Sequence[Metar]] | None,
    history: _StationErrors,
) -> tuple[TempDistribution, list[float], float] | None:
    """The live lane's distribution at ``entry_hour``, its day-ahead maxima
    and the entry moment; ``None`` when the forecasts or METARs miss the day."""
    day_text = event.day.isoformat()
    daily = [v[day_text] for v in runs.maxima.values() if day_text in v]
    if not daily:
        return None
    zone = station_zone(runs)
    start = datetime.combine(event.day, datetime.min.time(), zone)
    moment = (start + timedelta(hours=entry_hour)).timestamp()
    if observations is None:
        dist = _forecast_only(daily, history.bias(), lane, entry_hour, history)
        return dist, daily, moment
    covered, floor = _observed_max(
        observations.get(event.icao, ()), event.day, zone, moment
    )
    remaining = runs.remaining_maxima(day_text, entry_hour)
    if not covered or not remaining:
        return None
    if floor is None:  # before the day's first METAR: the live lane's fallback
        bias = applied_bias(history.bias(), entry_hour, lane.peak_hour)
        dist = _forecast_only(remaining, bias, lane, entry_hour, history)
        return dist, daily, moment
    mu, _ = intraday_mean(
        remaining,
        runs.maxima_before(day_text, entry_hour),
        floor,
        lane.today_error_weight,
    )
    dist = TempDistribution(mu=mu, sigma=lane.intraday_sigma, floor=floor)
    return dist, daily, moment


def backtest_weather(
    events: Sequence[EventHistory],
    forecasts: Mapping[str, PreviousRuns],
    lane: WeatherLane,
    *,
    bankroll: float = 1000.0,
    half_spread: float = 0.01,
    entry_hour: int = 0,
    observations: Mapping[str, Sequence[Metar]] | None = None,
) -> BacktestResult:
    """Replay the weather lane; see the module docstring.

    With ``observations`` (METARs per station) the replay is **intraday**:
    at ``entry_hour`` local time the observed maximum so far is the floor and
    the day-ahead forecast of the remaining hours is the mean, exactly as the
    live lane prices the day. Events whose day the METARs do not cover are
    skipped, so an intraday result is never mixed with forecast-only trades.
    """
    records: list[dict[str, Any]] = []
    trades = 0
    net = 0.0
    learnt: dict[str, _StationErrors] = {}
    scored: list[tuple[float, float, float, bool]] = []
    used = 0
    for event in sorted(events, key=lambda e: e.day):
        runs = forecasts.get(event.icao)
        if runs is None:
            continue
        history = learnt.setdefault(event.icao, _StationErrors())
        built = _distribution(event, runs, lane, entry_hour, observations, history)
        if built is None:
            continue
        dist, daily, moment = built
        used += 1
        for bucket in event.buckets:
            price = bucket.price_at(moment)
            if price is not None:
                p_yes = dist.range_probability(bucket.low, bucket.high, event.unit)
                blended = blend(p_yes, price, lane.market_weight)
                scored.append((p_yes, price, blended, bucket.won))
            records_added, pnl = _trade_bucket(
                event, bucket, dist, lane, moment, bankroll, half_spread
            )
            records.extend(records_added)
            trades += len(records_added) // 2
            net += pnl
        settled = event.settled_celsius()
        if settled is not None:  # learnt only after the event: no look-ahead
            history.errors.append(settled - statistics.fmean(daily))
    return BacktestResult(
        records, trades, used, round(net, 4), scores=brier_scores(scored)
    )


def _trade_bucket(
    event: EventHistory,
    bucket: BucketHistory,
    dist: TempDistribution,
    lane: WeatherLane,
    moment: float,
    bankroll: float,
    half_spread: float,
) -> tuple[list[dict[str, Any]], float]:
    price = bucket.price_at(moment)
    if price is None:
        return [], 0.0
    p_yes = dist.range_probability(bucket.low, bucket.high, event.unit)
    fee = FeeSchedule(rate=bucket.fee_rate)
    out: list[dict[str, Any]] = []
    pnl = 0.0
    for token, model_p, mid, won in (
        (bucket.yes_token, p_yes, price, bucket.won),
        (bucket.no_token, 1.0 - p_yes, 1.0 - price, not bucket.won),
    ):
        cost = min(0.999, mid + half_spread)
        if not lane.min_price <= cost <= lane.max_price:
            continue
        if net_edge(model_p, cost, fee) > lane.max_edge:
            continue
        fair = blend(model_p, mid, lane.market_weight)
        if net_edge(fair, cost, fee) < lane.min_edge:
            continue
        kelly = kelly_fraction(fair, cost + fee.per_share(cost))
        notional = min(lane.max_notional, lane.kelly_fraction * kelly * bankroll)
        if notional < lane.min_notional:
            continue
        payout = 1.0 if won else 0.0
        entry_fee = round(notional / cost * fee.per_share(cost), 5)
        out.extend(
            round_trip(
                instrument_id=token,
                name=f"{event.city} {event.day:%d %b} {bucket.label(event.unit)}"
                + ("" if token == bucket.yes_token else " No"),
                strategy=LANE_WEATHER,
                reason=f"backtest weather {fair:.2f} vs {cost:.2f}",
                entry_time=moment,
                entry_price=cost,
                notional=notional,
                entry_fee=entry_fee,
                exit_time=event.end_time,
                exit_price=payout,
                metrics={
                    "fair": round(fair, 4),
                    "model_p": round(model_p, 4),
                    "mu_c": round(dist.mu, 2),
                    "sigma_c": round(dist.sigma, 2),
                    "icao": event.icao,
                },
            )
        )
        pnl += notional / cost * payout - notional - entry_fee
    return out, pnl


__all__ = [
    "BucketHistory",
    "DEFAULT_WEATHER_HISTORY",
    "EventHistory",
    "backtest_weather",
    "collect_weather",
    "day_ahead_forecasts",
    "load_events",
    "station_metars",
]
