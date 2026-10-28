"""JSONL helpers and backtest trades written in trading-core's audit format.

A backtest writes the same ``trade`` records a paper run writes (built with
trading-core's own :func:`~trading_core.engine.records.trade_record`), so
``trading-core-audit pnl / cuts / verdict`` judge a backtest exactly like a
paper run, with the same rules file (docs/RESEARCH.md, docs/GO-NO-GO.md).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from trading_core.engine.records import ACTION_BUY, ACTION_SELL, trade_record
from trading_core.module.base import (
    COST_SOURCE_MODELLED,
    Fill,
    Side,
    TradeCosts,
)
from trading_core.positions import Position

MODE_BACKTEST = "backtest"


def read_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    """Every JSON object in ``path`` (missing file: nothing; bad lines skipped)."""
    target = Path(path)
    if not target.is_file():
        return
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def append_jsonl(path: str | Path, rows: Iterable[Mapping[str, Any]]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            count += 1
    return count


def envelope(payload: Mapping[str, Any], timestamp: float) -> dict[str, Any]:
    """The audit-trail line around a trade payload (as the engine writes it)."""
    return {
        "timestamp": float(timestamp),
        "type": "trade",
        "state": MODE_BACKTEST,
        "payload": dict(payload),
    }


def round_trip(
    *,
    instrument_id: str,
    name: str,
    strategy: str,
    reason: str,
    entry_time: float,
    entry_price: float,
    notional: float,
    entry_fee: float,
    exit_time: float,
    exit_price: float,
    exit_fee: float = 0.0,
    exit_reason: str = "resolved",
    metrics: Mapping[str, Any] | None = None,
    module: str = "polymarket",
) -> list[dict[str, Any]]:
    """A buy and its closing sell as two audit envelopes."""
    size = notional / entry_price
    buy = Fill(
        instrument_id=instrument_id,
        side=Side.BUY,
        size=size,
        price=entry_price,
        notional=notional,
        costs=TradeCosts({"fee": entry_fee}, source=COST_SOURCE_MODELLED),
        reference="backtest",
        timestamp=entry_time,
        simulated=True,
    )
    position = Position(
        instrument_id=instrument_id,
        size=size,
        entry_price=entry_price,
        cost_basis=notional,
        name=name,
        entry_costs=entry_fee,
        booked_net=-entry_fee,
        opened_at=entry_time,
        strategy=strategy,
        entry_reason=reason,
        entry_metrics=dict(metrics or {}),
    )
    common: dict[str, Any] = {
        "quote_symbol": "USDC",
        "mode": MODE_BACKTEST,
        "module": module,
    }
    records = [
        envelope(
            trade_record(
                action=ACTION_BUY,
                fill=buy,
                position=position,
                cost=notional,
                proceeds=0.0,
                reason=reason,
                timestamp=entry_time,
                entry_metrics=metrics,
                **common,
            ),
            entry_time,
        )
    ]
    sell = Fill(
        instrument_id=instrument_id,
        side=Side.SELL,
        size=size,
        price=exit_price,
        notional=size * exit_price,
        costs=TradeCosts({"fee": exit_fee}, source=COST_SOURCE_MODELLED),
        reference="backtest",
        timestamp=exit_time,
        simulated=True,
    )
    released = position.remove_units(size)
    records.append(
        envelope(
            trade_record(
                action=ACTION_SELL,
                fill=sell,
                position=position,
                cost=released,
                proceeds=sell.notional,
                reason=exit_reason,
                timestamp=exit_time,
                **common,
            ),
            exit_time,
        )
    )
    return records


__all__ = [
    "MODE_BACKTEST",
    "append_jsonl",
    "envelope",
    "read_jsonl",
    "round_trip",
]
