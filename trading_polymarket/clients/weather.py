"""Free weather data: Open-Meteo forecasts and Aviation Weather Center METARs.

Polymarket's daily-temperature markets resolve on the highest **routine METAR**
temperature at one airport (ICAO code in the market text) on the station's
local date; the hourly ``T`` remark (tenths of °C) governs, else the whole-°C
body group, and ``SPECI`` reports do not count. :func:`metar_temperature`
implements exactly that reading, so the module's "max so far" is the number
the market will resolve on.

Sources (all keyless, docs/DATA-SOURCES.md):

* ``aviationweather.gov/api/data/metar`` - recent METARs (JSON, ``rawOb``);
* ``aviationweather.gov/api/data/stationinfo`` - station latitude/longitude;
* ``api.open-meteo.com/v1/forecast`` - hourly and daily forecasts per model
  (``timezone=auto`` returns the station's IANA zone);
* ``ensemble-api.open-meteo.com/v1/ensemble`` - ensemble members (spread);
* ``previous-runs-api.open-meteo.com`` - what the model said *the day before*
  (``temperature_2m_previous_day1``), used to measure each station's bias.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from trading_polymarket.clients.http import JsonHttp, build_url

AWC_URL = "https://aviationweather.gov"
OPEN_METEO_URL = "https://api.open-meteo.com"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com"
DEFAULT_MODELS = ("ecmwf_ifs025", "gfs_seamless", "icon_seamless")

_T_GROUP = re.compile(r"\bT([01])(\d{3})([01]\d{3})?\b")
_BODY_GROUP = re.compile(r"(?<![\w/])(M?\d{1,2})/(M?\d{1,2})?(?![\w/])")


def metar_temperature(raw: str) -> float | None:
    """°C from a raw METAR: the ``T`` remark (tenths), else the body group."""
    remark = _T_GROUP.search(raw.split(" RMK ", 1)[1] if " RMK " in raw else "")
    if remark:
        value = int(remark.group(2)) / 10.0
        return -value if remark.group(1) == "1" else value
    body = raw.split(" RMK ", 1)[0]
    match = _BODY_GROUP.search(body)
    if match is None:
        return None
    text = match.group(1)
    return -float(text[1:]) if text.startswith("M") else float(text)


@dataclass(frozen=True)
class Metar:
    icao: str
    obs_time: float
    temperature: float | None
    raw: str
    routine: bool = True


@dataclass(frozen=True)
class Station:
    icao: str
    name: str
    latitude: float
    longitude: float
    elevation: float = 0.0
    country: str = ""


@dataclass(frozen=True)
class Forecast:
    """One forecast fetch for one point; temperatures in the requested unit."""

    timezone: str
    utc_offset_seconds: int
    daily_max: Mapping[str, Mapping[str, float]]  # model -> date -> max
    hourly: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    unit: str = "celsius"

    def model_maxima(self, date: str) -> dict[str, float]:
        return {
            model: values[date]
            for model, values in self.daily_max.items()
            if date in values
        }

    def remaining_max(self, model: str, date: str, after_hour: int) -> float | None:
        """Highest hourly value on ``date`` from local hour ``after_hour`` on."""
        values = [
            temp
            for stamp, temp in self.hourly.get(model, {}).items()
            if stamp.startswith(date) and int(stamp[11:13]) >= after_hour
        ]
        return max(values) if values else None


@dataclass(frozen=True)
class PreviousRuns:
    """Day-ahead forecasts of past dates (``previous_day1``), per model."""

    timezone: str
    utc_offset_seconds: int
    maxima: Mapping[str, Mapping[str, float]]  # model -> local date -> max
    hourly: Mapping[str, Mapping[str, float]] = field(default_factory=dict)

    def mean(self, date: str) -> float | None:
        values = [v[date] for v in self.maxima.values() if date in v]
        return sum(values) / len(values) if values else None

    def remaining_maxima(self, date: str, after_hour: int) -> list[float]:
        """Per model: the day-ahead forecast's highest value from ``after_hour`` on."""
        found = []
        for values in self.hourly.values():
            rest = [
                temp
                for stamp, temp in values.items()
                if stamp.startswith(date) and int(stamp[11:13]) >= after_hour
            ]
            if rest:
                found.append(max(rest))
        return found


def _model_series(
    block: Mapping[str, Any], prefix: str, models: Sequence[str]
) -> dict[str, dict[str, float]]:
    times = [str(t) for t in block.get("time") or []]
    series: dict[str, dict[str, float]] = {}
    for model in models:
        # One model: Open-Meteo drops the suffix; several: one key each.
        values = block.get(f"{prefix}_{model}")
        if values is None and len(models) == 1:
            values = block.get(prefix)
        if not isinstance(values, list):
            continue
        series[model] = {
            stamp: float(v)
            for stamp, v in zip(times, values, strict=False)
            if v is not None
        }
    return series


class WeatherClient:
    def __init__(
        self,
        http: JsonHttp,
        *,
        awc_url: str = AWC_URL,
        open_meteo_url: str = OPEN_METEO_URL,
        ensemble_url: str = ENSEMBLE_URL,
        previous_runs_url: str = PREVIOUS_RUNS_URL,
    ) -> None:
        self.http = http
        self.awc_url = awc_url
        self.open_meteo_url = open_meteo_url
        self.ensemble_url = ensemble_url
        self.previous_runs_url = previous_runs_url

    # -- Aviation Weather Center ---------------------------------------------
    async def metars(self, icao: str, *, hours: int = 30) -> list[Metar]:
        payload = await self.http.get_json(
            build_url(
                self.awc_url,
                "/api/data/metar",
                {"ids": icao, "format": "json", "hours": hours},
            )
        )
        found: list[Metar] = []
        for row in payload if isinstance(payload, list) else []:
            if not isinstance(row, Mapping):
                continue
            raw = str(row.get("rawOb") or "")
            try:
                obs = float(row["obsTime"])
            except (KeyError, TypeError, ValueError):
                continue
            kind = str(row.get("metarType") or "")
            found.append(
                Metar(
                    icao=str(row.get("icaoId") or icao),
                    obs_time=obs,
                    temperature=metar_temperature(raw),
                    raw=raw,
                    routine=kind != "SPECI" and not raw.startswith("SPECI"),
                )
            )
        found.sort(key=lambda m: m.obs_time)
        return found

    async def station(self, icao: str) -> Station | None:
        payload = await self.http.get_json(
            build_url(
                self.awc_url, "/api/data/stationinfo", {"ids": icao, "format": "json"}
            )
        )
        for row in payload if isinstance(payload, list) else []:
            if isinstance(row, Mapping) and row.get("lat") is not None:
                return Station(
                    icao=str(row.get("icaoId") or icao),
                    name=str(row.get("site") or ""),
                    latitude=float(row["lat"]),
                    longitude=float(row["lon"]),
                    elevation=float(row.get("elev") or 0.0),
                    country=str(row.get("country") or ""),
                )
        return None

    # -- Open-Meteo -----------------------------------------------------------
    async def forecast(
        self,
        latitude: float,
        longitude: float,
        *,
        models: Sequence[str] = DEFAULT_MODELS,
        unit: str = "celsius",
        days: int = 3,
        past_days: int = 0,
    ) -> Forecast:
        payload = await self.http.get_json(
            build_url(
                self.open_meteo_url,
                "/v1/forecast",
                {
                    "latitude": round(latitude, 4),
                    "longitude": round(longitude, 4),
                    "daily": "temperature_2m_max",
                    "hourly": "temperature_2m",
                    "models": ",".join(models),
                    "timezone": "auto",
                    "temperature_unit": unit,
                    "forecast_days": days,
                    "past_days": past_days or None,
                },
            )
        )
        return Forecast(
            timezone=str(payload.get("timezone") or "UTC"),
            utc_offset_seconds=int(payload.get("utc_offset_seconds") or 0),
            daily_max=_model_series(
                payload.get("daily") or {}, "temperature_2m_max", models
            ),
            hourly=_model_series(payload.get("hourly") or {}, "temperature_2m", models),
            unit=unit,
        )

    async def ensemble_maxima(
        self,
        latitude: float,
        longitude: float,
        date: str,
        *,
        model: str = "ecmwf_ifs025",
        unit: str = "celsius",
        days: int = 3,
    ) -> list[float]:
        """Every ensemble member's daily maximum on ``date``."""
        payload = await self.http.get_json(
            build_url(
                self.ensemble_url,
                "/v1/ensemble",
                {
                    "latitude": round(latitude, 4),
                    "longitude": round(longitude, 4),
                    "daily": "temperature_2m_max",
                    "models": model,
                    "timezone": "auto",
                    "temperature_unit": unit,
                    "forecast_days": days,
                },
            )
        )
        daily = payload.get("daily") or {}
        times = [str(t) for t in daily.get("time") or []]
        if date not in times:
            return []
        index = times.index(date)
        return [
            float(values[index])
            for key, values in daily.items()
            if key.startswith("temperature_2m_max")
            and isinstance(values, list)
            and index < len(values)
            and values[index] is not None
        ]

    async def previous_day_maxima(
        self,
        latitude: float,
        longitude: float,
        *,
        models: Sequence[str] = DEFAULT_MODELS,
        unit: str = "celsius",
        past_days: int = 14,
    ) -> PreviousRuns:
        """Per model and local date: the daily max forecast one day earlier.

        Built from ``temperature_2m_previous_day1`` (the run issued the day
        before), so it is what a trader could have known - no hindsight.
        """
        payload = await self.http.get_json(
            build_url(
                self.previous_runs_url,
                "/v1/forecast",
                {
                    "latitude": round(latitude, 4),
                    "longitude": round(longitude, 4),
                    "hourly": "temperature_2m_previous_day1",
                    "models": ",".join(models),
                    "timezone": "auto",
                    "temperature_unit": unit,
                    "past_days": past_days,
                    "forecast_days": 1,
                },
            )
        )
        hourly = _model_series(
            payload.get("hourly") or {}, "temperature_2m_previous_day1", models
        )
        maxima: dict[str, dict[str, float]] = {}
        for model, values in hourly.items():
            per_day = maxima.setdefault(model, {})
            for stamp, value in values.items():
                day = stamp[:10]
                per_day[day] = max(value, per_day.get(day, float("-inf")))
        return PreviousRuns(
            timezone=str(payload.get("timezone") or "UTC"),
            utc_offset_seconds=int(payload.get("utc_offset_seconds") or 0),
            maxima=maxima,
            hourly=hourly,
        )


__all__ = [
    "DEFAULT_MODELS",
    "Forecast",
    "Metar",
    "PreviousRuns",
    "Station",
    "WeatherClient",
    "metar_temperature",
]
