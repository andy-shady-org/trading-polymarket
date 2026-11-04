"""Backfill crypto Up/Down markets: every trade, the outcome, spot by the second.

``trading-polymarket updown-history --asset btc --window 5m --start
2026-10-05 --end 2026-11-04`` collects, for each UTC day, every market of
that asset and window (FEAT-146):

* **the markets**: their slugs are ``<asset>-updown-<window>-<start>``, the
  window's start in Unix seconds, so a day's are known without a listing;
  Gamma gives each settled one's outcome and the exact start and end prices
  it settled on (``eventMetadata.priceToBeat`` / ``finalPrice``, Chainlink's
  60-second average) and its fee;
* **the trades**: every taker order as it filled, to the second
  (:mod:`trading_polymarket.clients.data_api`), the prints a backtest can
  buy or sell at;
* **spot**: the asset's one-second closes on Binance
  (:mod:`trading_polymarket.clients.spot`), the path between the start and
  end prices.

A day is written once, whole, when every market in it has been read:
``<dir>/<asset>-<window>/<YYYY-MM-DD>.jsonl.gz`` (one market a line) and
``<dir>/spot/<SYMBOL>-<YYYY-MM-DD>.json.gz``. A day still running is left
out, and a day already on disk is skipped, so a collection is resumed or
extended by running it again; a day that could not be read whole is
reported and left for the next run. A market line::

    {"slug", "condition_id", "start", "end", "winner", "price_to_beat",
     "final_price", "fee_rate", "volume",
     "trades": [[t, outcome, side, price, size, wallet], ...]}

``outcome`` is 0 for Up and 1 for Down, ``side`` 1 for a buy and -1 for a
sale, ``t`` seconds from the market's start. Markets Gamma has not settled
(no winner yet) are left out of the day and counted.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from trading_polymarket.clients.data_api import DataApiClient, TradePrint
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.spot import SpotClient

DEFAULT_UPDOWN_DIR = "data/updown"
WINDOWS = {"5m": 300, "15m": 900}
SPOT_SYMBOLS = {
    "btc": "BTCUSDT",
    "eth": "ETHUSDT",
    "sol": "SOLUSDT",
    "xrp": "XRPUSDT",
    "doge": "DOGEUSDT",
    "bnb": "BNBUSDT",
}
OUTCOMES = ("Up", "Down")
DAY = 86400

Progress = Callable[[str], None]


@dataclass(frozen=True)
class UpDownMarket:
    """One settled market and its trades (``t`` from the market's start)."""

    slug: str
    condition_id: str
    start: float
    end: float
    winner: int
    price_to_beat: float | None
    final_price: float | None
    fee_rate: float
    volume: float
    trades: tuple[tuple[float, int, int, float, float, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "condition_id": self.condition_id,
            "start": self.start,
            "end": self.end,
            "winner": self.winner,
            "price_to_beat": self.price_to_beat,
            "final_price": self.final_price,
            "fee_rate": self.fee_rate,
            "volume": self.volume,
            "trades": [list(t) for t in self.trades],
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> UpDownMarket:
        return cls(
            slug=str(row["slug"]),
            condition_id=str(row["condition_id"]),
            start=float(row["start"]),
            end=float(row["end"]),
            winner=int(row["winner"]),
            price_to_beat=_number(row.get("price_to_beat")),
            final_price=_number(row.get("final_price")),
            fee_rate=float(row.get("fee_rate") or 0.0),
            volume=float(row.get("volume") or 0.0),
            trades=tuple(
                (float(t), int(o), int(s), float(p), float(z), str(w))
                for t, o, s, p, z, w in row.get("trades") or ()
            ),
        )


@dataclass(frozen=True)
class SpotDay:
    """A day's one-second closes (``closes[i]`` at ``start + i``; ``None``:
    no candle that second)."""

    symbol: str
    start: float
    closes: tuple[float | None, ...]

    def price_at(self, moment: float) -> float | None:
        """The last close at or before ``moment`` within the day."""
        index = int(moment - self.start)
        if index < 0:
            return None
        for i in range(min(index, len(self.closes) - 1), -1, -1):
            if self.closes[i] is not None:
                return self.closes[i]
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "start": self.start, "closes": list(self.closes)}

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> SpotDay:
        return cls(
            symbol=str(row["symbol"]),
            start=float(row["start"]),
            closes=tuple(None if c is None else float(c) for c in row["closes"]),
        )


@dataclass
class CollectResult:
    days_written: int = 0
    days_skipped: int = 0
    days_failed: list[str] = field(default_factory=list)
    markets: int = 0
    unsettled: int = 0
    trades: int = 0


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def day_start(day: date) -> float:
    return datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()


def market_slugs(asset: str, window: str, day: date) -> list[str]:
    """The slugs of every market of ``asset`` and ``window`` starting on ``day``."""
    step = WINDOWS[window]
    first = int(day_start(day))
    return [f"{asset}-updown-{window}-{first + i * step}" for i in range(DAY // step)]


def day_path(directory: str | Path, asset: str, window: str, day: date) -> Path:
    return Path(directory) / f"{asset}-{window}" / f"{day.isoformat()}.jsonl.gz"


def spot_path(directory: str | Path, symbol: str, day: date) -> Path:
    return Path(directory) / "spot" / f"{symbol}-{day.isoformat()}.json.gz"


def _winner(raw: Mapping[str, Any]) -> int | None:
    """The index of the outcome that paid 1 (``None``: not settled)."""
    try:
        outcomes = tuple(json.loads(raw["outcomes"]))
        prices = [float(p) for p in json.loads(raw["outcomePrices"])]
    except (KeyError, TypeError, ValueError):
        return None
    if outcomes != OUTCOMES or sorted(prices) != [0.0, 1.0]:
        return None
    return prices.index(1.0)


def _settled(raw: Mapping[str, Any], step: int) -> UpDownMarket | None:
    """A Gamma market as a settled Up/Down market (no trades yet)."""
    winner = _winner(raw)
    slug = str(raw.get("slug") or "")
    if winner is None or not raw.get("conditionId"):
        return None
    start = float(slug.rsplit("-", 1)[-1])
    events = raw.get("events")
    event = events[0] if isinstance(events, list) and events else {}
    meta = event.get("eventMetadata") if isinstance(event, Mapping) else None
    meta = meta if isinstance(meta, Mapping) else {}
    fee = raw.get("feeSchedule")
    fee = fee if isinstance(fee, Mapping) else {}
    return UpDownMarket(
        slug=slug,
        condition_id=str(raw["conditionId"]),
        start=start,
        end=start + step,
        winner=winner,
        price_to_beat=_number(meta.get("priceToBeat")),
        final_price=_number(meta.get("finalPrice")),
        fee_rate=float(fee.get("rate") or 0.0),
        volume=float(raw.get("volumeNum") or raw.get("volume") or 0.0),
    )


def _compact(prints: Sequence[TradePrint], start: float) -> tuple:
    return tuple(
        (
            round(p.timestamp - start),
            p.outcome_index,
            1 if p.side == "BUY" else -1,
            round(p.price, 6),
            round(p.size, 6),
            p.wallet,
        )
        for p in prints
    )


async def _with_trades(
    data: DataApiClient, gate: asyncio.Semaphore, market: UpDownMarket
) -> UpDownMarket:
    async with gate:
        prints = await data.trades(market.condition_id)
    return UpDownMarket(**{**market.__dict__, "trades": _compact(prints, market.start)})


def _spot_day(
    symbol: str, day: date, candles: Sequence[tuple[float, float]]
) -> SpotDay:
    start = day_start(day)
    closes: list[float | None] = [None] * DAY
    for t, close in candles:
        index = int(t - start)
        if 0 <= index < DAY:
            closes[index] = close
    return SpotDay(symbol=symbol, start=start, closes=tuple(closes))


def _write_gzip(path: Path, lines: Sequence[str]) -> None:
    """Write whole or not at all: a temporary file renamed into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    with gzip.open(temporary, "wt", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")
    os.replace(temporary, path)


async def collect_day(
    gamma: GammaClient,
    data: DataApiClient,
    spot: SpotClient,
    *,
    asset: str,
    window: str,
    day: date,
    directory: str | Path = DEFAULT_UPDOWN_DIR,
    concurrency: int = 6,
) -> CollectResult:
    """Read one day whole and write it (see the module docstring)."""
    step = WINDOWS[window]
    raw = await gamma.raw_markets_by_slugs(market_slugs(asset, window, day))
    settled = [m for m in (_settled(r, step) for r in raw) if m is not None]
    settled.sort(key=lambda m: m.start)
    gate = asyncio.Semaphore(max(1, concurrency))
    markets = await asyncio.gather(*(_with_trades(data, gate, m) for m in settled))
    symbol = SPOT_SYMBOLS[asset]
    start = day_start(day)
    candles = await spot.seconds(symbol, start=start, end=start + DAY)
    _write_gzip(
        spot_path(directory, symbol, day),
        [json.dumps(_spot_day(symbol, day, candles).to_dict(), separators=(",", ":"))],
    )
    _write_gzip(
        day_path(directory, asset, window, day),
        [json.dumps(m.to_dict(), separators=(",", ":")) for m in markets],
    )
    return CollectResult(
        days_written=1,
        markets=len(markets),
        unsettled=len(raw) - len(settled),
        trades=sum(len(m.trades) for m in markets),
    )


def _quiet(_: str) -> None:
    return None


def days(start: date, end: date) -> list[date]:
    """``start`` up to, not including, ``end``."""
    return [start + timedelta(days=i) for i in range((end - start).days)]


async def collect(
    gamma: GammaClient,
    data: DataApiClient,
    spot: SpotClient,
    *,
    asset: str,
    window: str,
    start: date,
    end: date,
    directory: str | Path = DEFAULT_UPDOWN_DIR,
    concurrency: int = 6,
    progress: Progress | None = None,
    now: float | None = None,
) -> CollectResult:
    """Every day in ``[start, end)`` that is over and not yet on disk (a day
    still running is left out: its last markets have not settled)."""
    if asset not in SPOT_SYMBOLS:
        raise ValueError(f"unknown asset {asset!r} (one of {', '.join(SPOT_SYMBOLS)})")
    if window not in WINDOWS:
        raise ValueError(f"unknown window {window!r} (one of {', '.join(WINDOWS)})")
    total = CollectResult()
    say = progress or _quiet
    moment = time.time() if now is None else now
    for day in days(start, end):
        if day_start(day) + DAY > moment:
            say(f"{day}: not over yet, left out")
            continue
        if day_path(directory, asset, window, day).is_file():
            total.days_skipped += 1
            continue
        try:
            result = await collect_day(
                gamma,
                data,
                spot,
                asset=asset,
                window=window,
                day=day,
                directory=directory,
                concurrency=concurrency,
            )
        except Exception as exc:  # leave the day for the next run
            total.days_failed.append(day.isoformat())
            say(f"{day}: not written ({exc})")
            continue
        total.days_written += 1
        total.markets += result.markets
        total.unsettled += result.unsettled
        total.trades += result.trades
        unsettled = f", {result.unsettled} not settled" if result.unsettled else ""
        say(f"{day}: {result.markets} markets, {result.trades} trades{unsettled}")
    return total


def _read_gzip_lines(path: Path) -> Iterator[str]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        yield from (line for line in handle if line.strip())


def load_markets(
    directory: str | Path,
    asset: str,
    window: str,
    *,
    start: date | None = None,
    end: date | None = None,
) -> Iterator[UpDownMarket]:
    """The collected markets, oldest first, of the days in ``[start, end)``."""
    folder = Path(directory) / f"{asset}-{window}"
    for path in sorted(folder.glob("*.jsonl.gz")):
        day = date.fromisoformat(path.name.split(".")[0])
        if (start is not None and day < start) or (end is not None and day >= end):
            continue
        for line in _read_gzip_lines(path):
            yield UpDownMarket.from_dict(json.loads(line))


def load_spot(directory: str | Path, symbol: str, day: date) -> SpotDay | None:
    path = spot_path(directory, symbol, day)
    if not path.is_file():
        return None
    return SpotDay.from_dict(json.loads(next(_read_gzip_lines(path))))


def parse_day(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC).date()


__all__ = [
    "DEFAULT_UPDOWN_DIR",
    "SPOT_SYMBOLS",
    "WINDOWS",
    "CollectResult",
    "SpotDay",
    "UpDownMarket",
    "collect",
    "collect_day",
    "day_path",
    "day_start",
    "days",
    "load_markets",
    "load_spot",
    "market_slugs",
    "parse_day",
    "spot_path",
]
