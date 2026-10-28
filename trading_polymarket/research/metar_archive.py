"""A growing METAR archive, so intraday backtests can reach further back.

The Aviation Weather Center keeps only about 15 days of METARs, which caps
the weather lane's intraday backtest (``backtest weather --intraday``) at two
weeks. ``trading-polymarket metars`` appends every station's new reports to
``data/metars/<ICAO>.jsonl`` (deduplicated by observation time); run it daily
(cron) during the pilot and the archive grows by a day per day.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from trading_polymarket.clients.weather import Metar, WeatherClient
from trading_polymarket.research.records import append_jsonl, read_jsonl

DEFAULT_METAR_DIR = "data/metars"


def load_station(directory: str | Path, icao: str) -> list[Metar]:
    rows = []
    for raw in read_jsonl(Path(directory) / f"{icao}.jsonl"):
        try:
            rows.append(Metar(**raw))
        except TypeError:
            continue
    rows.sort(key=lambda m: m.obs_time)
    return rows


def load_archive(directory: str | Path) -> dict[str, list[Metar]]:
    root = Path(directory)
    if not root.is_dir():
        return {}
    return {path.stem: load_station(root, path.stem) for path in root.glob("*.jsonl")}


def merge(
    *sources: Mapping[str, Sequence[Metar]],
) -> dict[str, list[Metar]]:
    """One list per station, deduplicated by observation time, oldest first."""
    merged: dict[str, dict[float, Metar]] = {}
    for source in sources:
        for icao, metars in source.items():
            bucket = merged.setdefault(icao, {})
            for metar in metars:
                bucket.setdefault(metar.obs_time, metar)
    return {
        icao: sorted(b.values(), key=lambda m: m.obs_time) for icao, b in merged.items()
    }


async def archive(
    client: WeatherClient,
    icaos: Iterable[str],
    *,
    directory: str | Path = DEFAULT_METAR_DIR,
    hours: int = 360,
    concurrency: int = 4,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Append each station's unseen METARs; returns how many were new."""
    gate = asyncio.Semaphore(concurrency)

    async def one(icao: str) -> int:
        async with gate:
            try:
                fresh = await client.metars(icao, hours=hours)
            except Exception as exc:  # keep archiving the other stations
                if progress is not None:
                    progress(f"{icao}: {exc}")
                return 0
        known = {m.obs_time for m in load_station(directory, icao)}
        new = [m for m in fresh if m.obs_time not in known]
        return append_jsonl(Path(directory) / f"{icao}.jsonl", (asdict(m) for m in new))

    counts = await asyncio.gather(*(one(i) for i in sorted(set(icaos))))
    return sum(counts)


__all__ = ["DEFAULT_METAR_DIR", "archive", "load_archive", "load_station", "merge"]
