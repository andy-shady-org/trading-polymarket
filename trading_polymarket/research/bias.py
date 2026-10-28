"""Per-station forecast bias: how far the day-ahead forecast misses the METAR max.

Open-Meteo forecasts a grid cell; Polymarket settles on one airport's hourly
METARs. The gap is systematic per station (coastal airports, urban heat,
hourly sampling missing the true peak), so the weather lane adds each
station's measured bias to its forecast and uses the spread of the misses as
its base uncertainty.

For every complete local day in the window (AWC keeps about 15 days of
METARs) the builder compares the highest routine METAR with the mean of the
models' ``previous_day1`` maxima - the forecast a trader had the day before -
and writes ``{"stations": {ICAO: {"bias", "sd", "mae", "n"}}}``. Run it
weekly (``trading-polymarket bias``); the table's sha256 is recorded in run
provenance through the lane settings.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_polymarket.clients.weather import DEFAULT_MODELS, WeatherClient
from trading_polymarket.strategies.weather import station_zone

MIN_HOURS_OBSERVED = 18  # a day with fewer routine hours is incomplete


async def station_errors(
    client: WeatherClient,
    icao: str,
    station: Mapping[str, Any],
    *,
    models: Sequence[str] = DEFAULT_MODELS,
    days: int = 14,
    now: float | None = None,
) -> dict[str, float]:
    """``{local date: observed max - day-ahead forecast}`` for complete days."""
    runs = await client.previous_day_maxima(
        float(station["lat"]), float(station["lon"]), models=models, past_days=days
    )
    metars = await client.metars(icao, hours=24 * (days + 1))
    zone = station_zone(runs)
    today = datetime.fromtimestamp(time.time() if now is None else now, zone).date()
    maxima: dict[str, float] = {}
    hours: dict[str, set[int]] = {}
    for metar in metars:
        if not metar.routine or metar.temperature is None:
            continue
        local = datetime.fromtimestamp(metar.obs_time, zone)
        if local.date() >= today:
            continue
        key = local.date().isoformat()
        maxima[key] = max(metar.temperature, maxima.get(key, float("-inf")))
        hours.setdefault(key, set()).add(local.hour)
    errors: dict[str, float] = {}
    for day, observed in maxima.items():
        forecast = runs.mean(day)
        if forecast is None or len(hours[day]) < MIN_HOURS_OBSERVED:
            continue
        errors[day] = observed - forecast
    return dict(sorted(errors.items()))


def summarise(errors: Mapping[str, float]) -> dict[str, float]:
    values = list(errors.values())
    if not values:
        return {"bias": 0.0, "sd": 0.0, "mae": 0.0, "n": 0}
    return {
        "bias": round(statistics.fmean(values), 3),
        "sd": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
        "mae": round(statistics.fmean(abs(v) for v in values), 3),
        "n": len(values),
    }


async def build_bias_table(
    client: WeatherClient,
    stations: Mapping[str, Mapping[str, Any]],
    *,
    models: Sequence[str] = DEFAULT_MODELS,
    days: int = 14,
    concurrency: int = 4,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    gate = asyncio.Semaphore(concurrency)
    table: dict[str, Any] = {}
    failures: dict[str, str] = {}

    async def one(icao: str) -> None:
        async with gate:
            try:
                errors = await station_errors(
                    client, icao, stations[icao], models=models, days=days
                )
            except Exception as exc:  # report and carry on with the rest
                failures[icao] = str(exc)
                return
        table[icao] = {**summarise(errors), "errors": errors}
        if progress is not None:
            progress(f"{icao}: {table[icao]['n']} days, bias {table[icao]['bias']}")

    await asyncio.gather(*(one(icao) for icao in sorted(stations)))
    return {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "models": list(models),
        "days": days,
        "stations": dict(sorted(table.items())),
        "failures": failures,
    }


def save_table(table: Mapping[str, Any], path: str | Path) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n")
    return str(target)


__all__ = ["build_bias_table", "save_table", "station_errors", "summarise"]
