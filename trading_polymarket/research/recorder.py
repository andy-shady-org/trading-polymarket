"""Dry-run recorder: run the lanes on live data and log what they would do.

``trading-polymarket record`` runs the module's pipeline every ``interval``
seconds **without trading** and appends, per cycle, every signal (with its
entry metrics and the top of book) and a count of rejections by stage to
``data/record/<UTC date>.jsonl``. It needs no engine, no balance and no
risk state, so it can run beside a paper run to build a larger sample of
what each lane sees, and its files feed later research (docs/RESEARCH.md).
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_polymarket.module import PolymarketModule
from trading_polymarket.research.records import append_jsonl

DEFAULT_RECORD_DIR = "data/record"


async def record_cycle(module: PolymarketModule) -> dict[str, Any]:
    pipeline = module.pipeline()
    now = module.clock()
    if pipeline is None:
        return {"timestamp": now, "signals": [], "rejections": {}, "errors": []}
    result = await pipeline.run()
    return {
        "timestamp": now,
        "candidates": result.candidates,
        "signals": [
            {
                "instrument_id": s.instrument_id,
                "name": s.name,
                "strategy": s.strategy,
                "notional": s.notional,
                "limit_price": s.limit_price,
                "edge": s.edge,
                "metrics": dict(s.metrics),
            }
            for s in result.signals
        ],
        "rejections": dict(Counter(r.stage for r in result.rejections)),
        "errors": list(result.errors),
    }


async def record(
    module: PolymarketModule,
    *,
    directory: str | Path = DEFAULT_RECORD_DIR,
    cycles: int = 1,
    interval: float = 300.0,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Run ``cycles`` recording cycles; returns the number of signals logged."""
    pause = sleep or asyncio.sleep
    total = 0
    for index in range(cycles):
        started = time.monotonic()
        row = await record_cycle(module)
        day = datetime.fromtimestamp(row["timestamp"], UTC).strftime("%Y-%m-%d")
        append_jsonl(Path(directory) / f"{day}.jsonl", [row])
        total += len(row["signals"])
        if progress is not None:
            progress(
                f"cycle {index + 1}/{cycles}: {len(row['signals'])} signals, "
                f"{sum(row['rejections'].values())} rejections"
            )
        if index + 1 < cycles:
            await pause(max(0.0, interval - (time.monotonic() - started)))
    return total


__all__ = ["DEFAULT_RECORD_DIR", "record", "record_cycle"]
