"""Collect resolved markets and their price histories (free APIs only).

``trading-polymarket history --start 2026-08-01 --end 2026-10-01`` lists the
markets that closed in the window (Gamma, ``closed=true``), keeps resolved
binary ones above a volume floor, fetches each first token's hourly price
series (CLOB ``prices-history`` over a window ending at the close) and
appends one JSON line per market to ``data/history/markets.jsonl``. Only the last
``lookback_hours`` (96 by default) before the close are kept: the lanes and
the calibration look at most 72 hours ahead. Re-running skips markets
already collected, so a collection can be resumed or extended.

Each line holds everything calibration and backtests need and nothing else::

    {"market_id", "question", "token_ids", "outcomes", "winner",
     "end_time", "volume", "fee_rate", "fee_exponent", "neg_risk",
     "event_slug", "group_item_title", "tags", "history": [[t, p], ...]}

``p`` is the first token's price; the second token's is ``1 - p``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.markets import Market
from trading_polymarket.research.records import append_jsonl, read_jsonl

DEFAULT_HISTORY_PATH = "data/history/markets.jsonl"


@dataclass(frozen=True)
class HistoryRow:
    """One resolved market with its price series (first token)."""

    market_id: str
    token_ids: tuple[str, ...]
    winner: int
    end_time: float
    history: tuple[tuple[float, float], ...]
    fee_rate: float = 0.0
    fee_exponent: float = 1.0
    volume: float = 0.0
    question: str = ""
    tags: tuple[str, ...] = ()
    event_slug: str = ""
    group_item_title: str = ""

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> HistoryRow:
        return cls(
            market_id=str(row["market_id"]),
            token_ids=tuple(str(t) for t in row["token_ids"]),
            winner=int(row["winner"]),
            end_time=float(row["end_time"]),
            history=tuple((float(t), float(p)) for t, p in row.get("history") or []),
            fee_rate=float(row.get("fee_rate") or 0.0),
            fee_exponent=float(row.get("fee_exponent") or 1.0),
            volume=float(row.get("volume") or 0.0),
            question=str(row.get("question") or ""),
            tags=tuple(str(t) for t in row.get("tags") or ()),
            event_slug=str(row.get("event_slug") or ""),
            group_item_title=str(row.get("group_item_title") or ""),
        )

    def price_at(self, moment: float, token_index: int = 0) -> float | None:
        """The token's last printed price at or before ``moment``."""
        price: float | None = None
        for t, p in self.history:
            if t > moment:
                break
            price = p
        if price is None:
            return None
        return price if token_index == 0 else 1.0 - price


def market_row(market: Market, history: Iterable[tuple[float, float]]) -> dict:
    winner = next(i for i, p in enumerate(market.outcome_prices) if p == 1.0)
    return {
        "market_id": market.market_id,
        "question": market.question,
        "token_ids": list(market.token_ids),
        "outcomes": list(market.outcomes),
        "winner": winner,
        "end_time": market.end_time,
        "volume": market.volume,
        "fee_rate": market.fee.rate,
        "fee_exponent": market.fee.exponent,
        "neg_risk": market.neg_risk,
        "event_slug": market.event_slug,
        "group_item_title": market.group_item_title,
        "tags": list(market.tags),
        "history": [[round(t), round(p, 5)] for t, p in history],
    }


def load_rows(path: str | Path = DEFAULT_HISTORY_PATH) -> list[HistoryRow]:
    rows = []
    for raw in read_jsonl(path):
        try:
            rows.append(HistoryRow.from_dict(raw))
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r.end_time)
    return rows


def _windows(start: date, end: date, days: int) -> list[tuple[str, str]]:
    out = []
    cursor = start
    while cursor < end:
        stop = min(end, cursor + timedelta(days=days))
        out.append((f"{cursor.isoformat()}T00:00:00Z", f"{stop.isoformat()}T00:00:00Z"))
        cursor = stop
    return out


async def collect(
    gamma: GammaClient,
    clob: ClobClient,
    *,
    start: date,
    end: date,
    path: str | Path = DEFAULT_HISTORY_PATH,
    min_volume: float = 1000.0,
    tag_slug: str | None = None,
    max_markets: int = 2000,
    max_pages: int = 20,
    concurrency: int = 4,
    window_days: int = 3,
    lookback_hours: float = 96.0,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Append newly resolved markets in ``[start, end)``; returns how many."""
    seen = {str(r.get("market_id")) for r in read_jsonl(path)}
    picked: list[Market] = []
    windows = _windows(start, end, window_days)
    # Spread the sample over the whole range, not the first windows only.
    per_window = max(1, max_markets // max(1, len(windows)))
    for low, high in windows:
        taken = 0
        markets = await gamma.closed_markets(
            end_date_min=low, end_date_max=high, max_pages=max_pages, tag_slug=tag_slug
        )
        for market in markets:
            if (
                market.resolved
                and len(market.token_ids) == 2
                and market.end_time is not None
                and market.volume >= min_volume
                and market.market_id not in seen
                and taken < per_window
            ):
                seen.add(market.market_id)
                picked.append(market)
                taken += 1
        if progress is not None:
            progress(f"{low[:10]}..{high[:10]}: {len(picked)} markets so far")
    gate = asyncio.Semaphore(concurrency)

    async def one(market: Market) -> dict | None:
        async with gate:
            try:
                end_time = float(market.end_time or 0.0)
                points = await clob.prices_history(
                    market.token_ids[0],
                    start=end_time - lookback_hours * 3600.0,
                    end=end_time + 3600.0,
                )
            except Exception as exc:  # skip the market, keep the collection going
                if progress is not None:
                    progress(f"{market.market_id}: {exc}")
                return None
        if not points:
            return None
        return market_row(market, ((p.t, p.p) for p in points))

    written = 0
    batch = 50
    for index in range(0, len(picked), batch):
        rows = await asyncio.gather(*(one(m) for m in picked[index : index + batch]))
        written += append_jsonl(path, (r for r in rows if r is not None))
        if progress is not None:
            progress(f"price histories: {written} written")
    return written


def parse_day(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC).date()


__all__ = [
    "DEFAULT_HISTORY_PATH",
    "HistoryRow",
    "collect",
    "load_rows",
    "market_row",
    "parse_day",
]
