"""The weather lane: daily-temperature markets against forecasts and METARs.

Each Polymarket event "Highest temperature in <City> on <Month Day>?" has one
market per whole-degree bucket ("14°C or below", "15°C", "74-75°F", "92°F or
higher"). It resolves on the highest routine METAR temperature at the airport
named in the rules (ICAO code in brackets), on the station's local date,
rounded half up to whole degrees of the market's unit.

The model (docs/STRATEGIES.md has the derivation):

* ``M`` - the highest routine METAR so far on the local date (none before the
  day starts); the final maximum can never be lower;
* ``R`` - the maximum of the hours still to come, ``Normal(mu, sigma)``:
  ``mu`` is the multi-model forecast (daily max, or the max of the remaining
  hourly values on the day itself) plus the station's measured bias;
  ``sigma`` grows with lead time and with disagreement between models;
* the final value is ``max(M, R)``, so
  ``P(final < x) = 1[x > M] * Phi((x - mu) / sigma)`` and a bucket
  ``[lo, hi]`` (after half-up rounding) has probability
  ``P(final < hi + 0.5) - P(final < lo - 0.5)``.

Late in the local day ``R`` falls below ``M`` and the distribution collapses
onto the observed maximum: this is where the edge is largest and most certain.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from importlib import resources
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trading_core.strategy.pipeline import Analyst, Candidate, Scout, Signal

from trading_polymarket.catalogue import BookCache, MarketCatalogue
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.weather import (
    Forecast,
    Metar,
    PreviousRuns,
    WeatherClient,
)
from trading_polymarket.config import LANE_WEATHER, WeatherLane
from trading_polymarket.markets import Market
from trading_polymarket.strategies.common import (
    KEY_FAIR,
    KEY_LANE,
    KEY_MARKET,
    net_edge,
    plan_buy,
    token_ask,
    token_mid,
)

WEATHER_TAG = "highest-temperature"
_TITLE = re.compile(r"Highest temperature in (.+?) on ([A-Za-z]+) (\d{1,2})\b")
_ICAO = re.compile(r"\(([A-Z]{4})\)")
_NOAA_SITE = re.compile(r"timeseries\?site=([A-Za-z0-9]{4})\b")
_RANGE = re.compile(r"(-?\d+)\s*-\s*(-?\d+)\s*°\s*([CF])")
_BELOW = re.compile(r"(-?\d+)\s*°\s*([CF])\s+or\s+(?:below|lower)", re.I)
_ABOVE = re.compile(r"(-?\d+)\s*°\s*([CF])\s+or\s+(?:higher|above)", re.I)
_SINGLE = re.compile(r"(-?\d+)\s*°\s*([CF])")
_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "january february march april may june july august september "
            "october november december"
        ).split(),
        start=1,
    )
}


def round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def to_unit(celsius: float, unit: str) -> float:
    return celsius * 9.0 / 5.0 + 32.0 if unit == "F" else celsius


def to_celsius(value: float, unit: str) -> float:
    return (value - 32.0) * 5.0 / 9.0 if unit == "F" else value


def blend(model: float, market: float | None, weight: float) -> float:
    """Shrink the model towards the market mid (no mid: the model alone)."""
    if market is None:
        return model
    return (1.0 - weight) * model + weight * market


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass(frozen=True)
class Bucket:
    """Whole-degree range ``[low, high]`` in ``unit``; ``None`` is open-ended."""

    low: int | None
    high: int | None
    unit: str
    market: Market

    @classmethod
    def parse(cls, title: str, market: Market) -> Bucket | None:
        text = title.replace("º", "°")
        if match := _RANGE.search(text):
            return cls(int(match[1]), int(match[2]), match[3].upper(), market)
        if match := _BELOW.search(text):
            return cls(None, int(match[1]), match[2].upper(), market)
        if match := _ABOVE.search(text):
            return cls(int(match[1]), None, match[2].upper(), market)
        if match := _SINGLE.search(text):
            return cls(int(match[1]), int(match[1]), match[2].upper(), market)
        return None

    def contains(self, value: int) -> bool:
        return (self.low is None or value >= self.low) and (
            self.high is None or value <= self.high
        )

    @property
    def label(self) -> str:
        if self.low is None:
            return f"<={self.high}°{self.unit}"
        if self.high is None:
            return f">={self.low}°{self.unit}"
        if self.low == self.high:
            return f"{self.low}°{self.unit}"
        return f"{self.low}-{self.high}°{self.unit}"


def _event_day(month: int, day_of_month: int, end: float | None) -> date | None:
    """The event's local date; the year comes from the market's end time."""
    anchor = datetime.fromtimestamp(end if end is not None else time.time(), UTC)
    try:
        day = date(anchor.year, month, day_of_month)
    except ValueError:
        return None
    gap = (day - anchor.date()).days
    if gap > 180:  # "December 31" on a market that ends in January
        day = day.replace(year=anchor.year - 1)
    elif gap < -180:  # "January 1" on a market that ends in December
        day = day.replace(year=anchor.year + 1)
    return day


def _station(text: str, *, legacy: bool) -> str | None:
    """The settlement airport's ICAO code; ``None`` for other sources."""
    if "METAR" in text and (match := _ICAO.search(text)):
        return match[1]
    if legacy and (match := _NOAA_SITE.search(text)):
        return match[1].upper()
    return None


@dataclass(frozen=True)
class WeatherEvent:
    event_id: str
    title: str
    city: str
    day: date
    icao: str
    unit: str
    buckets: tuple[Bucket, ...]

    @classmethod
    def parse(
        cls,
        event: Mapping[str, Any],
        markets: Sequence[Market],
        *,
        legacy: bool = False,
    ) -> WeatherEvent | None:
        """The event, or ``None`` when it is not a METAR-settled temperature event.

        ``legacy`` also accepts the rules used until October 2026 (NOAA's
        station time series, ``timeseries?site=<icao>``), which read the same
        airport observations; research uses it, live trading does not.
        """
        title = str(event.get("title") or "")
        match = _TITLE.search(title)
        if not match or not markets:
            return None
        month = _MONTHS.get(match[2].lower())
        if month is None:
            return None
        text = " ".join(
            [str(event.get("description") or "")] + [m.description for m in markets]
        )
        icao = _station(text, legacy=legacy)
        if icao is None:
            return None
        end = next((m.end_time for m in markets if m.end_time), None)
        day = _event_day(month, int(match[3]), end)
        if day is None:
            return None
        buckets = [
            b
            for b in (
                Bucket.parse(m.group_item_title or m.question, m) for m in markets
            )
            if b is not None
        ]
        units = {b.unit for b in buckets}
        if len(units) != 1:
            return None
        return cls(
            event_id=str(event.get("id") or ""),
            title=title,
            city=match[1].strip(),
            day=day,
            icao=icao,
            unit=units.pop(),
            buckets=tuple(buckets),
        )

    def winner(self, celsius: float) -> Bucket | None:
        """The bucket a final maximum of ``celsius`` resolves to."""
        value = round_half_up(round(to_unit(celsius, self.unit), 6))
        return next((b for b in self.buckets if b.contains(value)), None)


@dataclass(frozen=True)
class TempDistribution:
    """``max(floor, Normal(mu, sigma))`` in °C, plus how it was built."""

    mu: float
    sigma: float
    floor: float | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def cdf(self, celsius: float) -> float:
        """``P(final < celsius)``."""
        if self.floor is not None and celsius <= self.floor:
            return 0.0
        if self.sigma <= 0:
            return 1.0 if celsius > self.mu else 0.0
        return normal_cdf((celsius - self.mu) / self.sigma)

    def range_probability(self, low: int | None, high: int | None, unit: str) -> float:
        """Probability the settled whole-degree value lands in ``[low, high]``."""
        upper = 1.0 if high is None else self.cdf(to_celsius(high + 0.5, unit))
        lower = 0.0 if low is None else self.cdf(to_celsius(low - 0.5, unit))
        return min(1.0, max(0.0, upper - lower))

    def bucket_probability(self, bucket: Bucket) -> float:
        return self.range_probability(bucket.low, bucket.high, bucket.unit)


DAY_AHEAD_HOURS = 30.0  # a day-ahead run is ~30 h before the local afternoon peak
MIN_BIAS_DAYS = 10


def lead_sigma(
    lane: WeatherLane,
    lead_hours: float,
    *,
    spread: float = 0.0,
    measured_sd: float | None = None,
) -> float:
    """Uncertainty (°C) of the day's maximum ``lead_hours`` before the peak.

    The curve is ``sigma_min + sigma_per_day × lead / 24``. A station's
    measured day-ahead error (``measured_sd``, from the bias table) already
    contains the models' disagreement, so with one the curve is rescaled to
    equal it at :data:`DAY_AHEAD_HOURS` and the spread is not added again;
    without one, the spread between models is added in quadrature.
    """
    curve = lane.sigma_min + lane.sigma_per_day * max(0.0, lead_hours) / 24.0
    if measured_sd is not None:
        day_ahead = lane.sigma_min + lane.sigma_per_day * DAY_AHEAD_HOURS / 24.0
        sigma = measured_sd * curve / day_ahead
    else:
        sigma = math.hypot(curve, spread)
    return max(lane.min_remaining_sigma, sigma)


def load_stations(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Station coordinates (``data/stations.json`` shipped with the package)."""
    if path is not None:
        return dict(json.loads(Path(path).read_text()))
    text = resources.files("trading_polymarket").joinpath("data/stations.json")
    return dict(json.loads(text.read_text()))


def load_bias(path: str) -> dict[str, dict[str, float]]:
    """Per-station bias table written by ``trading-polymarket bias``."""
    if not path or not Path(path).is_file():
        return {}
    return dict(json.loads(Path(path).read_text()).get("stations", {}))


def station_zone(forecast: Forecast | PreviousRuns) -> tzinfo:
    """The station's IANA zone (with DST); a fixed offset if unknown."""
    try:
        return ZoneInfo(forecast.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone(timedelta(seconds=forecast.utc_offset_seconds))


class WeatherModel:
    """Builds a :class:`TempDistribution` per event, caching every fetch."""

    def __init__(
        self,
        client: WeatherClient,
        lane: WeatherLane,
        *,
        stations: Mapping[str, Mapping[str, Any]] | None = None,
        bias: Mapping[str, Mapping[str, float]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client = client
        self.lane = lane
        self.stations: dict[str, Mapping[str, Any]] = dict(
            load_stations() if stations is None else stations
        )
        self.bias = dict(load_bias(lane.bias_path) if bias is None else bias)
        self.clock = clock
        self._forecasts: dict[str, tuple[Forecast, float]] = {}
        self._metars: dict[str, tuple[list[Metar], float]] = {}

    async def station(self, icao: str) -> Mapping[str, Any] | None:
        known = self.stations.get(icao)
        if known is not None:
            return known
        found = await self.client.station(icao)
        if found is None:
            return None
        entry = {"lat": found.latitude, "lon": found.longitude, "name": found.name}
        self.stations[icao] = entry
        return entry

    async def forecast(self, icao: str, station: Mapping[str, Any]) -> Forecast:
        now = self.clock()
        cached = self._forecasts.get(icao)
        if cached and now - cached[1] < self.lane.forecast_ttl_seconds:
            return cached[0]
        forecast = await self.client.forecast(
            float(station["lat"]),
            float(station["lon"]),
            models=self.lane.models,
            days=self.lane.lead_days + 2,
            past_days=1,
        )
        self._forecasts[icao] = (forecast, now)
        return forecast

    async def metars(self, icao: str) -> list[Metar]:
        now = self.clock()
        cached = self._metars.get(icao)
        if cached and now - cached[1] < self.lane.metar_ttl_seconds:
            return cached[0]
        metars = await self.client.metars(icao, hours=48)
        self._metars[icao] = (metars, now)
        return metars

    def _collapsed(self, floor: float, **metrics: Any) -> TempDistribution:
        """The day's maximum is (almost) known: what was observed."""
        return TempDistribution(
            mu=floor,
            sigma=self.lane.min_remaining_sigma,
            floor=floor,
            metrics={**metrics, "observed_max": floor},
        )

    async def distribution(self, event: WeatherEvent) -> TempDistribution | None:
        station = await self.station(event.icao)
        if station is None:
            return None
        forecast = await self.forecast(event.icao, station)
        zone = station_zone(forecast)
        now = self.clock()
        local_now = datetime.fromtimestamp(now, zone)
        lead_days = (event.day - local_now.date()).days
        day_text = event.day.isoformat()

        observed = [
            m.temperature
            for m in await self.metars(event.icao)
            if m.routine
            and m.temperature is not None
            and datetime.fromtimestamp(m.obs_time, zone).date() == event.day
        ]
        floor = max(observed) if observed else None

        if lead_days < 0:  # the local day is over: the observed max decides
            if floor is None:
                return None
            return self._collapsed(floor, lead_days=-1, local_hour=local_now.hour)

        bias_row = self.bias.get(event.icao, {})
        bias = float(bias_row.get("bias", 0.0))
        measured_sd = (
            float(bias_row["sd"])
            if bias_row.get("n", 0) >= MIN_BIAS_DAYS and bias_row.get("sd")
            else None
        )

        if lead_days == 0:
            values = [
                v
                for v in (
                    forecast.remaining_max(model, day_text, local_now.hour + 1)
                    for model in self.lane.models
                )
                if v is not None
            ]
        else:
            values = list(forecast.model_maxima(day_text).values())
        if not values:
            if floor is None:
                return None
            return self._collapsed(
                floor, lead_days=lead_days, hours_left=0, local_hour=local_now.hour
            )
        peak = datetime.combine(event.day, datetime.min.time(), zone) + timedelta(
            hours=self.lane.peak_hour
        )
        lead_hours = max(0.0, (peak.timestamp() - now) / 3600.0)
        spread = statistics.pstdev(values) if len(values) > 1 else 0.0
        sigma = lead_sigma(
            self.lane, lead_hours, spread=spread, measured_sd=measured_sd
        )
        mu = statistics.fmean(values) + bias
        return TempDistribution(
            mu=mu,
            sigma=sigma,
            floor=floor,
            metrics={
                "lead_days": lead_days,
                "local_hour": local_now.hour,
                "lead_hours": round(lead_hours, 2),
                "mu_c": round(mu, 2),
                "sigma_c": round(sigma, 2),
                "model_spread_c": round(spread, 2),
                "bias_c": round(bias, 2),
                "observed_max": floor,
                "models": len(values),
            },
        )


class WeatherScout(Scout):
    """Open temperature events whose buckets the model prices away from market."""

    name = "weather-events"

    def __init__(
        self,
        gamma: GammaClient,
        catalogue: MarketCatalogue,
        model: WeatherModel,
        lane: WeatherLane,
    ) -> None:
        self.gamma = gamma
        self.catalogue = catalogue
        self.model = model
        self.lane = lane
        self.last_events = 0
        self.disagreements = 0
        self.errors: list[str] = []

    async def events(self) -> list[WeatherEvent]:
        pages = max(1, math.ceil(self.lane.max_events / 100))
        found = []
        for raw, markets in await self.gamma.events(
            max_pages=pages, closed=False, tag_slug=WEATHER_TAG
        ):
            event = WeatherEvent.parse(raw, markets)
            if event is None:
                continue
            if self.lane.cities and event.city.lower() not in self.lane.cities:
                continue
            found.append(event)
            self.catalogue.put(markets)
        self.last_events = len(found)
        return found

    def _candidates(
        self, event: WeatherEvent, dist: TempDistribution
    ) -> list[tuple[float, Candidate]]:
        scored: list[tuple[float, Candidate]] = []
        for bucket in event.buckets:
            market = bucket.market
            if not market.tradable:
                continue
            p_yes = dist.bucket_probability(bucket)
            for token, model_p in (
                (market.yes_token, p_yes),
                (market.no_token, 1.0 - p_yes),
            ):
                ask = token_ask(market, token)
                mid = token_mid(market, token)
                if ask is None or not (
                    self.lane.min_price <= ask <= self.lane.max_price
                ):
                    continue
                if net_edge(model_p, ask, market.fee) > self.lane.max_edge:
                    self.disagreements += 1  # too good to be true: model error
                    continue
                fair = blend(model_p, mid, self.lane.market_weight)
                gap = net_edge(fair, ask, market.fee)
                if gap < self.lane.min_edge / 2:
                    continue
                candidate = Candidate(
                    instrument_id=token,
                    name=(
                        f"{event.city} {event.day:%d %b} {bucket.label} "
                        f"{market.outcome_of(token)}"
                    ),
                    source=self.name,
                    data={
                        KEY_LANE: LANE_WEATHER,
                        KEY_MARKET: market,
                        KEY_FAIR: fair,
                        "icao": event.icao,
                        "bucket": bucket.label,
                        "gamma_ask": ask,
                        "model_p": round(model_p, 4),
                        **dict(dist.metrics),
                    },
                )
                scored.append((gap, candidate))
        return scored

    async def _price(
        self, event: WeatherEvent, gate: asyncio.Semaphore
    ) -> list[tuple[float, Candidate]]:
        async with gate:
            try:
                dist = await self.model.distribution(event)
            except Exception as exc:  # one bad station must not stop the scan
                self.errors.append(f"{event.icao}: {exc}")
                return []
        if dist is None or not self._in_window(dist.metrics):
            return []
        return self._candidates(event, dist)

    def _in_window(self, metrics: Mapping[str, Any]) -> bool:
        """Lead within ``lead_days``; with ``min_local_hour``, only the event's
        own local day from that hour on (or after the day has ended)."""
        lead = int(metrics["lead_days"])
        if lead > self.lane.lead_days:
            return False
        if self.lane.min_local_hour <= 0 or lead < 0:
            return True
        return lead == 0 and int(metrics["local_hour"]) >= self.lane.min_local_hour

    async def discover(self) -> Sequence[Candidate]:
        self.errors = []
        self.disagreements = 0
        today = datetime.fromtimestamp(self.model.clock(), UTC).date()
        # Local dates differ from UTC by at most a day: skip anything further
        # out before spending a forecast request on it.
        events = [
            e
            for e in await self.events()
            if -1 <= (e.day - today).days <= self.lane.lead_days + 1
        ]
        gate = asyncio.Semaphore(self.lane.concurrency)
        batches = await asyncio.gather(*(self._price(e, gate) for e in events))
        scored = [item for batch in batches for item in batch]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [candidate for _, candidate in scored[: self.lane.max_candidates]]


class WeatherAnalyst(Analyst):
    """Re-prices a weather candidate on the live book and sizes the buy."""

    name = "weather-model"

    def __init__(self, books: BookCache, lane: WeatherLane, *, bankroll: float) -> None:
        self.books = books
        self.lane = lane
        self.bankroll = bankroll

    async def evaluate(
        self, candidate: Candidate, screening_metrics: Mapping[str, Any]
    ) -> Signal | None:
        market: Market = candidate.data[KEY_MARKET]
        fair = float(candidate.data[KEY_FAIR])
        book = await self.books.get(candidate.instrument_id)
        plan = plan_buy(
            book,
            fair,
            market.fee,
            self.lane,
            bankroll=self.bankroll,
            max_price=self.lane.max_price,
        )
        if plan is None:
            return None
        metrics = {
            key: value
            for key, value in candidate.data.items()
            if key not in (KEY_MARKET, KEY_LANE, KEY_FAIR)
        }
        return Signal(
            instrument_id=candidate.instrument_id,
            reason=f"weather fair {fair:.2f} vs {plan.average_price:.2f}",
            name=candidate.name,
            notional=plan.notional,
            limit_price=plan.limit,
            confidence=min(1.0, max(0.0, plan.edge * 4)),
            edge=plan.edge,
            strategy=LANE_WEATHER,
            metrics={**metrics, **plan.metrics(), KEY_FAIR: round(fair, 4)},
        )


__all__ = [
    "Bucket",
    "TempDistribution",
    "WEATHER_TAG",
    "WeatherAnalyst",
    "WeatherEvent",
    "WeatherModel",
    "WeatherScout",
    "blend",
    "lead_sigma",
    "load_bias",
    "load_stations",
    "normal_cdf",
    "round_half_up",
    "station_zone",
    "to_celsius",
    "to_unit",
]
