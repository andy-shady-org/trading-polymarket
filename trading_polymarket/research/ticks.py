"""Record crypto Up/Down books and spot to the millisecond (FEAT-147, FEAT-101).

``trading-polymarket ticks`` runs three loops until ``--hours`` pass or
``Ctrl-C``, record-only:

* **the book**: Polymarket's market WebSocket for the current and the next
  window of an asset (``book`` snapshots, ``price_change`` level updates,
  ``last_trade_price`` fills). The full book updates hundreds of times a
  second, so it is kept here and only its **top** is written, whenever the
  best bid or the best ask change (below); every fill is written with
  its transaction hash, which matches it to the data API's trade rows. The
  socket is closed a moment into each new window and opened again with that
  window's markets. A top is written when a best price changes, or when the
  size at a best ask of 10 c or less changes (the cheap side FEAT-147 buys;
  elsewhere size-only changes are 90% of the rows and are left out);
* **spot**: Binance's trade stream for the asset (by default the
  market-data mirror ``data-stream.binance.vision``), written whenever the
  price changes, with Binance's event and trade times;
* **a round trip** to the CLOB's host (``GET /time``) every 30 seconds:
  the floor under how fast an order of ours could reach the matching engine.

Every row starts with ``rx``, the local time in milliseconds the message
arrived. Files, one folder per UTC day (``<dir>/<YYYY-MM-DD>/``)::

    spot.jsonl.gz     [rx, event_ms, trade_ms, price]
    quotes.jsonl.gz   [rx, server_ms, key, bid, bid_size, ask, ask_size]
    trades.jsonl.gz   [rx, server_ms, key, side, price, size, tx_hash]
    markets.jsonl     {"rx", "slug", "start", "end", "condition_id", "tokens"}
    probes.jsonl      [rx, round_trip_ms, server_time]

``key`` is ``"<window start>:<outcome>"`` (0 Up, 1 Down); ``markets.jsonl``
maps each token to its key. A missing best price is ``null``.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from trading_core.ops.stream import run_websocket_stream, send_ws_message

from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.http import HttpError, JsonHttp
from trading_polymarket.research.updown import OUTCOMES, SPOT_SYMBOLS, WINDOWS

DEFAULT_TICKS_DIR = "data/ticks"
BOOK_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
SPOT_WS_URL = "wss://data-stream.binance.vision/ws/{symbol}@aggTrade"
CLOB_URL = "https://clob.polymarket.com"
PING_SECONDS = 5.0  # the venue closed a socket ~9 s after a connect without one
PROBE_SECONDS = 30.0
STATUS_SECONDS = 300.0
ROLL_SECONDS = 2.0
GZIPPED = frozenset({"spot", "quotes", "trades"})
CHEAP_ASK = 0.10

Clock = Callable[[], float]
Log = Callable[[str], None]
Top = tuple[float | None, float | None, float | None, float | None]


def ms(seconds: float) -> int:
    return int(round(seconds * 1000))


def day_of(rx_ms: int) -> str:
    return datetime.fromtimestamp(rx_ms / 1000, UTC).strftime("%Y-%m-%d")


class TickWriter:
    """Append rows to one file per name and UTC day; see the module docstring."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.counts: Counter[str] = Counter()
        self._open: dict[str, tuple[str, IO[str]]] = {}

    def _handle(self, name: str, day: str) -> IO[str]:
        current = self._open.get(name)
        if current is not None and current[0] == day:
            return current[1]
        if current is not None:
            current[1].close()
        folder = self.directory / day
        folder.mkdir(parents=True, exist_ok=True)
        handle: IO[str]
        if name in GZIPPED:
            handle = gzip.open(folder / f"{name}.jsonl.gz", "at", encoding="utf-8")
        else:
            handle = (folder / f"{name}.jsonl").open("a", encoding="utf-8")
        self._open[name] = (day, handle)
        return handle

    def write(self, name: str, row: Any, *, rx: int) -> None:
        handle = self._handle(name, day_of(rx))
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.counts[name] += 1

    def flush(self) -> None:
        for _, handle in self._open.values():
            handle.flush()

    def close(self) -> None:
        for _, handle in self._open.values():
            handle.close()
        self._open.clear()


@dataclass
class Book:
    """One token's book: price → size on each side."""

    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)

    def reset(self, bids: Any, asks: Any) -> None:
        self.bids = _levels(bids)
        self.asks = _levels(asks)

    def set(self, side: str, price: float, size: float) -> None:
        levels = self.bids if side == "BUY" else self.asks
        if size > 0:
            levels[price] = size
        else:
            levels.pop(price, None)

    def top(self) -> Top:
        bid = max(self.bids) if self.bids else None
        ask = min(self.asks) if self.asks else None
        return (
            bid,
            self.bids[bid] if bid is not None else None,
            ask,
            self.asks[ask] if ask is not None else None,
        )


def _levels(rows: Any) -> dict[float, float]:
    found: dict[float, float] = {}
    for row in rows if isinstance(rows, list) else []:
        try:
            price, size = float(row["price"]), float(row["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if size > 0:
            found[price] = size
    return found


@dataclass(frozen=True)
class WindowMarket:
    """One open Up/Down market and its tokens' keys."""

    slug: str
    start: int
    end: int
    condition_id: str
    tokens: Mapping[str, str]

    def to_dict(self, rx: int) -> dict[str, Any]:
        return {
            "rx": rx,
            "slug": self.slug,
            "start": self.start,
            "end": self.end,
            "condition_id": self.condition_id,
            "tokens": dict(self.tokens),
        }


def window_start(moment: float, length: int) -> int:
    return int(moment // length) * length


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def parse_window_market(raw: Mapping[str, Any], length: int) -> WindowMarket | None:
    """A Gamma market as a :class:`WindowMarket`, or ``None`` when it is not one."""
    slug = str(raw.get("slug") or "")
    outcomes = [str(o) for o in _json_list(raw.get("outcomes"))]
    tokens = [str(t) for t in _json_list(raw.get("clobTokenIds"))]
    try:
        start = int(slug.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return None
    if outcomes != list(OUTCOMES) or len(tokens) != 2:
        return None
    return WindowMarket(
        slug=slug,
        start=start,
        end=start + length,
        condition_id=str(raw.get("conditionId") or ""),
        tokens={token: f"{start}:{i}" for i, token in enumerate(tokens)},
    )


async def window_markets(
    gamma: GammaClient, asset: str, window: str, start: int
) -> list[WindowMarket]:
    """The open markets of the window starting at ``start`` and of the next."""
    length = WINDOWS[window]
    slugs = [f"{asset}-updown-{window}-{start + i * length}" for i in (0, 1)]
    raw = await gamma.raw_markets_by_slugs(slugs, closed=None)
    found = (parse_window_market(r, length) for r in raw)
    return sorted((m for m in found if m is not None), key=lambda m: m.start)


Resolver = Callable[[int], Awaitable[list[WindowMarket]]]


class _Host:
    """The callbacks trading-core's stream loop needs that both streams share."""

    stream_url = ""
    reconnect_delay_seconds = 0.5
    stream_heartbeat_seconds: float | None = 20.0
    stream_idle_timeout_seconds: float | None = 30.0

    def __init__(
        self, writer: TickWriter, *, clock: Clock, log: Log, stop: asyncio.Event
    ) -> None:
        self.writer = writer
        self.clock = clock
        self.log = log
        self.stop = stop
        self.messages = 0
        self.rolling = False

    def stream_stop_requested(self) -> bool:
        return self.stop.is_set()

    def stream_connect_url(self) -> str:
        return self.stream_url

    def stream_log(self, message: str, level: int = logging.INFO) -> None:
        self.log(message)

    def on_stream_error(self, message: str) -> None:
        self.log(message)

    def on_stream_exception(self, exc: Exception, backoff: float) -> None:
        self.log(f"{type(self).__name__}: {exc!r}; reconnecting in {backoff:g}s")

    def on_stream_ended(self) -> None:
        if not self.rolling:
            self.log(f"{type(self).__name__}: the stream ended; reconnecting")
        self.rolling = False

    def on_stream_closed(self) -> None:
        return None

    def rx(self) -> int:
        return ms(self.clock())


class SpotStream(_Host):
    """Binance trades: a row whenever the price changes."""

    def __init__(
        self,
        writer: TickWriter,
        url: str,
        *,
        clock: Clock,
        log: Log,
        stop: asyncio.Event,
    ) -> None:
        super().__init__(writer, clock=clock, log=log, stop=stop)
        self.stream_url = url
        self.last: float | None = None

    async def on_stream_connected(self, ws: Any) -> None:
        self.log(f"spot: connected to {self.stream_url}")

    async def on_stream_message(self, data: Any, ws: Any) -> None:
        rx = self.rx()
        try:
            price = float(data["p"])
            row = [rx, int(data["E"]), int(data["T"]), price]
        except (KeyError, TypeError, ValueError):
            return
        self.messages += 1
        if price != self.last:
            self.last = price
            self.writer.write("spot", row, rx=rx)


class BookStream(_Host):
    """Polymarket's market channel for the current and next window."""

    stream_url = BOOK_WS_URL
    stream_heartbeat_seconds = None  # the venue wants a "PING" text instead

    def __init__(
        self,
        writer: TickWriter,
        resolve: Resolver,
        length: int,
        *,
        clock: Clock,
        log: Log,
        stop: asyncio.Event,
        ping_seconds: float = PING_SECONDS,
    ) -> None:
        super().__init__(writer, clock=clock, log=log, stop=stop)
        self.resolve = resolve
        self.length = length
        self.ping_seconds = ping_seconds
        self.window = 0
        self.keys: dict[str, str] = {}
        self.books: dict[str, Book] = {}
        self.tops: dict[str, Top] = {}
        self._pinger: asyncio.Task[None] | None = None

    async def on_stream_connected(self, ws: Any) -> None:
        # The same offset as the roll check: a connection in a window's first
        # seconds takes the window just ended and the new one, then rolls.
        self.window = window_start(self.clock() - ROLL_SECONDS, self.length)
        markets = await self.resolve(self.window)
        rx = self.rx()
        self.keys = {t: k for m in markets for t, k in m.tokens.items()}
        self.books = {t: Book() for t in self.keys}
        self.tops = {}
        for market in markets:
            self.writer.write("markets", market.to_dict(rx), rx=rx)
        self.log(f"book: {', '.join(m.slug for m in markets) or 'no markets'}")
        await send_ws_message(ws, {"assets_ids": list(self.keys), "type": "market"})
        self._pinger = asyncio.create_task(self._ping(ws))

    async def _ping(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(self.ping_seconds)
            await ws.send_str("PING")

    def on_stream_closed(self) -> None:
        if self._pinger is not None:
            self._pinger.cancel()
            self._pinger = None

    async def on_stream_message(self, data: Any, ws: Any) -> None:
        rx = self.rx()
        for event in data if isinstance(data, list) else [data]:
            if isinstance(event, Mapping):
                self.messages += 1
                self._event(event, rx)
        if window_start(self.clock() - ROLL_SECONDS, self.length) != self.window:
            self.rolling = True
            await ws.close()  # the loop reconnects with the new window's markets

    def _event(self, event: Mapping[str, Any], rx: int) -> None:
        kind = event.get("event_type")
        server = _int(event.get("timestamp"))
        if kind == "book" or (kind is None and "bids" in event):
            self._book(event, server, rx)
        elif kind == "price_change" or "price_changes" in event:
            self._changes(event, server, rx)
        elif kind == "last_trade_price":
            self._trade(event, server, rx)

    def _book(self, event: Mapping[str, Any], server: int | None, rx: int) -> None:
        token = str(event.get("asset_id"))
        if token in self.books:
            self.books[token].reset(event.get("bids"), event.get("asks"))
            self._quote(token, server, rx)

    def _changes(self, event: Mapping[str, Any], server: int | None, rx: int) -> None:
        touched: list[str] = []
        for change in _price_changes(event):
            token = str(change.get("asset_id"))
            try:
                side = str(change["side"]).upper()
                price, size = float(change["price"]), float(change["size"])
            except (KeyError, TypeError, ValueError):
                continue
            if token in self.books:
                self.books[token].set(side, price, size)
                touched.append(token)
        for token in dict.fromkeys(touched):
            self._quote(token, server, rx)

    def _quote(self, token: str, server: int | None, rx: int) -> None:
        top = self.books[token].top()
        if _worth_writing(top, self.tops.get(token)):
            self.tops[token] = top
            self.writer.write("quotes", [rx, server, self.keys[token], *top], rx=rx)

    def _trade(self, event: Mapping[str, Any], server: int | None, rx: int) -> None:
        token = str(event.get("asset_id"))
        if token not in self.keys:
            return
        try:
            price, size = float(event["price"]), float(event["size"])
        except (KeyError, TypeError, ValueError):
            return
        side = str(event.get("side") or "").upper()
        tx = str(event.get("transaction_hash") or "").lower()
        row = [rx, server, self.keys[token], side, price, size, tx]
        self.writer.write("trades", row, rx=rx)


def _worth_writing(top: Top, last: Top | None) -> bool:
    """A best price moved, or the size at a cheap best ask changed."""
    if last is None or (top[0], top[2]) != (last[0], last[2]):
        return True
    ask = top[2]
    return ask is not None and ask <= CHEAP_ASK and top[3] != last[3]


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _price_changes(event: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The level updates of a ``price_change`` (old and new message shapes)."""
    changes = event.get("price_changes")
    if isinstance(changes, list):
        return [c for c in changes if isinstance(c, Mapping)]
    legacy = event.get("changes")
    if not isinstance(legacy, list):
        return []
    asset = event.get("asset_id")
    return [{"asset_id": asset, **c} for c in legacy if isinstance(c, Mapping)]


async def probe_once(
    http: JsonHttp, writer: TickWriter, *, clock: Clock, url: str
) -> float | None:
    """One ``GET /time`` round trip in milliseconds (``None`` when it failed)."""
    began = time.perf_counter()
    try:
        server = await http.get_json(url)
        round_trip: float | None = round((time.perf_counter() - began) * 1000, 1)
    except (HttpError, OSError, ValueError):
        server, round_trip = None, None
    rx = ms(clock())
    writer.write("probes", [rx, round_trip, server], rx=rx)
    return round_trip


async def _until(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        return


async def probe_loop(
    http: JsonHttp,
    writer: TickWriter,
    *,
    clock: Clock,
    stop: asyncio.Event,
    url: str = CLOB_URL + "/time",
    interval: float = PROBE_SECONDS,
) -> None:
    while not stop.is_set():
        await probe_once(http, writer, clock=clock, url=url)
        writer.flush()
        await _until(stop, interval)


async def status_loop(
    writer: TickWriter,
    hosts: Sequence[_Host],
    *,
    log: Log,
    stop: asyncio.Event,
    interval: float = STATUS_SECONDS,
) -> None:
    while not stop.is_set():
        await _until(stop, interval)
        counts = ", ".join(f"{n} {writer.counts[n]}" for n in sorted(writer.counts))
        seen = ", ".join(f"{type(h).__name__} {h.messages}" for h in hosts)
        log(f"recorded: {counts or 'nothing yet'} (messages: {seen})")


async def deadline(stop: asyncio.Event, hours: float | None) -> None:
    if hours:
        await _until(stop, hours * 3600)
        stop.set()


Runner = Callable[[Any], Awaitable[None]]


async def record(
    gamma: GammaClient,
    http: JsonHttp,
    *,
    asset: str = "btc",
    window: str = "5m",
    directory: str | Path = DEFAULT_TICKS_DIR,
    hours: float | None = None,
    spot_url: str | None = None,
    runner: Runner = run_websocket_stream,
    clock: Clock = time.time,
    log: Log = print,
    stop: asyncio.Event | None = None,
) -> Counter[str]:
    """Record until ``hours`` pass or the task is cancelled; the rows written."""
    if asset not in SPOT_SYMBOLS or window not in WINDOWS:
        raise ValueError(f"unknown asset or window: {asset} {window}")
    stop = stop or asyncio.Event()
    writer = TickWriter(directory)
    url = spot_url or SPOT_WS_URL.format(symbol=SPOT_SYMBOLS[asset].lower())

    async def resolve(start: int) -> list[WindowMarket]:
        return await window_markets(gamma, asset, window, start)

    common: dict[str, Any] = {"clock": clock, "log": log, "stop": stop}
    book = BookStream(writer, resolve, WINDOWS[window], **common)
    spot = SpotStream(writer, url, **common)
    try:
        await asyncio.gather(
            runner(book),
            runner(spot),
            probe_loop(http, writer, clock=clock, stop=stop),
            status_loop(writer, [book, spot], log=log, stop=stop),
            deadline(stop, hours),
        )
    finally:
        book.on_stream_closed()
        writer.close()
    return writer.counts


__all__ = [
    "BOOK_WS_URL",
    "CLOB_URL",
    "DEFAULT_TICKS_DIR",
    "SPOT_WS_URL",
    "Book",
    "BookStream",
    "SpotStream",
    "TickWriter",
    "WindowMarket",
    "day_of",
    "parse_window_market",
    "probe_loop",
    "probe_once",
    "record",
    "window_markets",
    "window_start",
]
