"""Record tennis and esports match books on both venues from listing (FEAT-168).

The 2026-10-30 study (``docs/dev/RESULTS.md``) found major-league sports
priced alike on Polymarket and Kalshi to half a cent; the only gaps worth a
look came **in the first hours after a match was listed**, in tennis and
esports, and an hourly price history could not show whether an ask stood
behind them. ``trading-polymarket sports-gaps record`` records exactly that,
record-only, every ``interval`` seconds (120 by default):

* **Listings:** Polymarket's newest moneyline markets (Gamma
  ``/markets/keyset``, ``sports_market_types=moneyline``, newest first) whose
  slug names a tennis or esports league (:data:`PM_LEAGUES`), and Kalshi's
  open events in its tennis and esports match series (:data:`KALSHI_SERIES`,
  ``/events`` with nested markets). Each listing is written once to
  ``listings.jsonl`` with the venue's own creation time.
* **Pairs:** a Polymarket match and a Kalshi event are the same game when
  their start times are within :data:`MAX_START_GAP_SECONDS` and each side's
  name on one venue is contained in a side's name on the other, one to one
  (Kalshi's ITF events name players by surname only). A match with two
  candidates is left unpaired and counted, never guessed. Each pair is
  written once to ``pairs.jsonl``.
* **Quotes:** for every pair, until its start plus
  :data:`RECORD_AFTER_START_SECONDS`: Polymarket's book of the first outcome
  (CLOB ``/book``; the second outcome's book is its mirror, ask = 1 - bid
  at the same size, checked on 2026-11-07) and Kalshi's best Yes bid and ask
  with their sizes for each side's market (from the same ``/events`` read).
  One row per pair per cycle in ``quotes.jsonl.gz``.

Files, one folder per UTC day (``<dir>/<YYYY-MM-DD>/``)::

    listings.jsonl   {"rx", "venue", "id", "sport", "league", "title",
                      "sides", "created", "start"}
    pairs.jsonl      {"rx", "pair", "sport", "pm_slug", "pm_tokens",
                      "pm_sides", "pm_created", "pm_fee", "kalshi_event",
                      "kalshi_tickers", "kalshi_sides", "kalshi_created",
                      "start"}
    quotes.jsonl.gz  [rx, pair, pm_bid, pm_bid_size, pm_ask, pm_ask_size,
                      k0_bid, k0_bid_size, k0_ask, k0_ask_size,
                      k1_bid, k1_bid_size, k1_ask, k1_ask_size]

``pm_*`` are the first outcome's (``pm_sides[0]``); ``k0`` is Kalshi's
market for ``pm_sides[0]``, ``k1`` for ``pm_sides[1]``. A missing price is
``null``. ``sports-gaps report`` (``research/sports_gaps_report.py``) reads
them. Nothing is traded; both venues are read keyless.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import re
import time
import unicodedata
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_polymarket.clients.clob import BookUnavailable, ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.http import HttpError, JsonHttp, build_url
from trading_polymarket.clients.kalshi import KALSHI_URL, dollars
from trading_polymarket.fees import FeeSchedule
from trading_polymarket.markets import parse_time

DEFAULT_SPORTS_DIR = "data/sports-gaps"
DEFAULT_INTERVAL_SECONDS = 120.0
# Newest Polymarket moneyline markets read a cycle (100 a page): 1,500 were
# 2.5 days of every sport on 2026-11-07, so 3 pages see each new one within
# a cycle and the first cycle sees the last day or so.
PM_PAGES = 3
# Polymarket slug prefixes of tennis and esports leagues (counted on the
# 1,500 newest moneyline markets, 2026-11-04 to 2026-11-07).
PM_LEAGUES: dict[str, str] = {
    "atp": "tennis",
    "wta": "tennis",
    "itf": "tennis",
    "cs2": "esports",
    "dota2": "esports",
    "val": "esports",
    "lol": "esports",
    "codmw": "esports",
    "mlbb": "esports",
    "ow": "esports",
}
# Kalshi's match-winner series of the same sports (``/series?category=Sports``,
# open events counted on 2026-11-07; CS2 had none open that day).
KALSHI_SERIES: dict[str, str] = {
    "KXATPMATCH": "tennis",
    "KXATPCHALLENGERMATCH": "tennis",
    "KXWTAMATCH": "tennis",
    "KXWTACHALLENGERMATCH": "tennis",
    "KXITFMATCH": "tennis",
    "KXITFWMATCH": "tennis",
    "KXCS2GAME": "esports",
    "KXDOTA2GAME": "esports",
    "KXVALORANTGAME": "esports",
    "KXLOLGAME": "esports",
    "KXCODGAME": "esports",
    "KXMLBBGAME": "esports",
    "KXOWGAME": "esports",
}
# Two listings of one game: Kalshi's ``occurrence_datetime`` and Polymarket's
# ``gameStartTime`` are both the scheduled start; tennis orders of play move.
MAX_START_GAP_SECONDS = 12 * 3600.0
# A pair is quoted until its scheduled start plus this (a live match keeps
# trading; the listing-time question is answered well before).
RECORD_AFTER_START_SECONDS = 3 * 3600.0
# Words that name no side ("Team LEISURE" is Kalshi's "LEISURE").
FILLER = frozenset({"team", "esports", "esport", "gaming", "club", "the", "fc"})
_WORD = re.compile(r"[a-z0-9]+")

Clock = Callable[[], float]
Log = Callable[[str], None]
Sleep = Callable[[float], Awaitable[Any]]
Quote = tuple[float | None, float | None, float | None, float | None]


def side_words(label: str) -> frozenset[str]:
    """A side's name as words: accents dropped, lower case, filler left out."""
    plain = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    return frozenset(w for w in _WORD.findall(plain.lower()) if w not in FILLER)


def same_side(a: str, b: str) -> bool:
    """One name's words are all in the other's ("Bertrand" in "Lea Bertrand")."""
    wa, wb = side_words(a), side_words(b)
    return bool(wa and wb) and (wa <= wb or wb <= wa)


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return list(value) if isinstance(value, list) else []


@dataclass(frozen=True)
class PmMatch:
    slug: str
    league: str
    sport: str
    question: str
    sides: tuple[str, str]
    tokens: tuple[str, str]
    created: float
    start: float
    fee: FeeSchedule

    @property
    def key(self) -> str:
        return self.slug

    def listing(self, rx: float) -> dict[str, Any]:
        return {
            "rx": rx,
            "venue": "polymarket",
            "id": self.slug,
            "sport": self.sport,
            "league": self.league,
            "title": self.question,
            "sides": list(self.sides),
            "created": self.created,
            "start": self.start,
        }


def parse_pm(raw: Mapping[str, Any]) -> PmMatch | None:
    """A two-sided tennis or esports moneyline market, or ``None``."""
    slug = str(raw.get("slug") or "")
    league = slug.split("-", 1)[0]
    sides = [str(s) for s in _json_list(raw.get("outcomes"))]
    tokens = [str(t) for t in _json_list(raw.get("clobTokenIds"))]
    created = parse_time(raw.get("createdAt"))
    start = parse_time(raw.get("gameStartTime"))
    if league not in PM_LEAGUES or len(sides) != 2 or len(tokens) != 2:
        return None
    if {s.lower() for s in sides} & {"yes", "no"} or created is None or start is None:
        return None
    return PmMatch(
        slug=slug,
        league=league,
        sport=PM_LEAGUES[league],
        question=str(raw.get("question") or ""),
        sides=(sides[0], sides[1]),
        tokens=(tokens[0], tokens[1]),
        created=created,
        start=start,
        fee=FeeSchedule.from_gamma(raw.get("feeSchedule"), default_rate=0.05),
    )


@dataclass(frozen=True)
class KalshiSide:
    ticker: str
    label: str
    quote: Quote


@dataclass(frozen=True)
class KalshiMatch:
    event: str
    series: str
    sport: str
    title: str
    sides: tuple[KalshiSide, KalshiSide]
    created: float
    start: float

    @property
    def key(self) -> str:
        return self.event

    def listing(self, rx: float) -> dict[str, Any]:
        return {
            "rx": rx,
            "venue": "kalshi",
            "id": self.event,
            "sport": self.sport,
            "league": self.series,
            "title": self.title,
            "sides": [s.label for s in self.sides],
            "created": self.created,
            "start": self.start,
        }


def _price(value: Any) -> float | None:
    """A Kalshi price; 0 bid and 1 ask mean no order on that side."""
    price = dollars(value)
    return price if price is not None and 0.0 < price < 1.0 else None


def kalshi_quote(market: Mapping[str, Any]) -> Quote:
    """(Yes bid, its size, Yes ask, its size) of a nested Kalshi market."""
    return (
        _price(market.get("yes_bid_dollars")),
        dollars(market.get("yes_bid_size_fp")),
        _price(market.get("yes_ask_dollars")),
        dollars(market.get("yes_ask_size_fp")),
    )


def parse_kalshi(event: Mapping[str, Any], series: str) -> KalshiMatch | None:
    """A two-market match event, or ``None``."""
    markets = [m for m in event.get("markets") or [] if isinstance(m, Mapping)]
    if len(markets) != 2 or series not in KALSHI_SERIES:
        return None
    created = [parse_time(m.get("created_time")) for m in markets]
    start = parse_time(markets[0].get("occurrence_datetime"))
    if start is None or None in created:
        return None
    sides = tuple(
        KalshiSide(
            str(m.get("ticker") or ""),
            str(m.get("yes_sub_title") or ""),
            kalshi_quote(m),
        )
        for m in markets
    )
    return KalshiMatch(
        event=str(event.get("event_ticker") or ""),
        series=series,
        sport=KALSHI_SERIES[series],
        title=str(event.get("title") or ""),
        sides=(sides[0], sides[1]),
        created=min(c for c in created if c is not None),
        start=start,
    )


def side_order(pm: PmMatch, kalshi: KalshiMatch) -> tuple[int, int] | None:
    """Kalshi's side index for each Polymarket side, or ``None`` when the two
    are not the same game."""
    if pm.sport != kalshi.sport or abs(pm.start - kalshi.start) > MAX_START_GAP_SECONDS:
        return None
    labels = [s.label for s in kalshi.sides]
    for order in ((0, 1), (1, 0)):
        if all(same_side(pm.sides[i], labels[order[i]]) for i in (0, 1)):
            return order
    return None


@dataclass(frozen=True)
class Pair:
    pm: PmMatch
    kalshi: KalshiMatch
    order: tuple[int, int]

    @property
    def key(self) -> str:
        return f"{self.pm.slug}|{self.kalshi.event}"

    def row(self, rx: float) -> dict[str, Any]:
        sides = [self.kalshi.sides[i] for i in self.order]
        return {
            "rx": rx,
            "pair": self.key,
            "sport": self.pm.sport,
            "pm_slug": self.pm.slug,
            "pm_tokens": list(self.pm.tokens),
            "pm_sides": list(self.pm.sides),
            "pm_created": self.pm.created,
            "pm_fee": self.pm.fee.to_dict(),
            "kalshi_event": self.kalshi.event,
            "kalshi_tickers": [s.ticker for s in sides],
            "kalshi_sides": [s.label for s in sides],
            "kalshi_created": self.kalshi.created,
            "start": self.pm.start,
        }


def pair_up(
    pms: Iterable[PmMatch], kalshis: Sequence[KalshiMatch]
) -> tuple[list[Pair], int]:
    """Pairs, and how many Polymarket matches had more than one candidate
    (left unpaired, never guessed)."""
    pairs, ambiguous = [], 0
    for pm in pms:
        found = [(k, o) for k in kalshis if (o := side_order(pm, k)) is not None]
        if len(found) == 1:
            pairs.append(Pair(pm, found[0][0], found[0][1]))
        elif found:
            ambiguous += 1
    return pairs, ambiguous


def day_of(rx: float) -> str:
    return datetime.fromtimestamp(rx, UTC).strftime("%Y-%m-%d")


class SportsWriter:
    """Append rows to the day's files; see the module docstring."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.counts: Counter[str] = Counter()

    def _path(self, rx: float, name: str) -> Path:
        folder = self.directory / day_of(rx)
        folder.mkdir(parents=True, exist_ok=True)
        return folder / name

    def rows(self, rx: float, name: str, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            return
        with self._path(rx, f"{name}.jsonl").open("a", encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(row, sort_keys=True) + "\n")
        self.counts[name] += len(rows)

    def quotes(self, rx: float, rows: Sequence[Sequence[Any]]) -> None:
        if not rows:
            return
        with gzip.open(
            self._path(rx, "quotes.jsonl.gz"), "at", encoding="utf-8"
        ) as out:
            for row in rows:
                out.write(json.dumps(list(row)) + "\n")
        self.counts["quotes"] += len(rows)


@dataclass
class Venues:
    """The two venues' reads, over one paced HTTP client."""

    gamma: GammaClient
    clob: ClobClient
    http: JsonHttp
    kalshi_url: str = KALSHI_URL
    series: Mapping[str, str] = field(default_factory=lambda: dict(KALSHI_SERIES))

    async def pm_matches(self, pages: int = PM_PAGES) -> list[PmMatch]:
        raw = await self.gamma.raw_markets(
            max_pages=pages,
            closed=False,
            sports_market_types="moneyline",
            order="createdAt",
            ascending=False,
        )
        return [m for m in (parse_pm(r) for r in raw) if m is not None]

    async def kalshi_matches(self) -> list[KalshiMatch]:
        found: list[KalshiMatch] = []
        for series in self.series:
            url = build_url(
                self.kalshi_url,
                "/events",
                {
                    "series_ticker": series,
                    "status": "open",
                    "with_nested_markets": True,
                    "limit": 200,
                },
            )
            payload = await self.http.get_json(url)
            events = payload.get("events") if isinstance(payload, Mapping) else None
            for event in events or []:
                match = (
                    parse_kalshi(event, series) if isinstance(event, Mapping) else None
                )
                if match is not None:
                    found.append(match)
        return found

    async def pm_quote(self, token: str) -> Quote:
        """(bid, size, ask, size) of the first outcome's book; ``None`` s when
        it has no book."""
        try:
            book = await self.clob.book(token)
        except BookUnavailable:
            return (None, None, None, None)
        bid = book.bids[0] if book.bids else None
        ask = book.asks[0] if book.asks else None
        return (
            bid.price if bid else None,
            bid.size if bid else None,
            ask.price if ask else None,
            ask.size if ask else None,
        )


@dataclass
class SportsRecorder:
    """One cycle: listings, pairs and a quote row per live pair."""

    venues: Venues
    writer: SportsWriter
    clock: Clock = time.time
    listed: set[str] = field(default_factory=set)
    pairs: dict[str, Pair] = field(default_factory=dict)
    written: set[str] = field(default_factory=set)
    ambiguous: int = 0
    errors: int = 0

    def _new_listings(
        self, pms: Sequence[PmMatch], kalshis: Sequence[KalshiMatch], rx: float
    ) -> None:
        rows = []
        items: list[PmMatch | KalshiMatch] = [*pms, *kalshis]
        for item in items:
            if item.key not in self.listed:
                self.listed.add(item.key)
                rows.append(item.listing(rx))
        self.writer.rows(rx, "listings", rows)

    def _new_pairs(self, found: Sequence[Pair], rx: float) -> None:
        """Live pairs are refreshed (Kalshi's quotes come with them); a pair
        is written once, and one past its window is not taken back."""
        live = [p for p in found if rx <= p.pm.start + RECORD_AFTER_START_SECONDS]
        new = [p for p in live if p.key not in self.written]
        self.pairs.update((p.key, p) for p in live)
        self.written.update(p.key for p in new)
        self.writer.rows(rx, "pairs", [p.row(rx) for p in new])

    async def _quote_rows(self, rx: float) -> list[list[Any]]:
        rows = []
        for pair in self.pairs.values():
            pm = await self.venues.pm_quote(pair.pm.tokens[0])
            k0, k1 = (pair.kalshi.sides[i].quote for i in pair.order)
            rows.append([rx, pair.key, *pm, *k0, *k1])
        return rows

    async def cycle(self) -> int:
        """One pass; returns the quote rows written."""
        rx = self.clock()
        pms = await self.venues.pm_matches()
        kalshis = await self.venues.kalshi_matches()
        self._new_listings(pms, kalshis, rx)
        found, self.ambiguous = pair_up(pms, kalshis)
        self._new_pairs(found, rx)
        rows = await self._quote_rows(rx)
        self.writer.quotes(rx, rows)
        return len(rows)

    def retire(self, now: float) -> None:
        """Drop pairs past their recording window (they are re-found, and
        skipped, while still listed)."""
        done = [
            k
            for k, p in self.pairs.items()
            if now > p.pm.start + RECORD_AFTER_START_SECONDS
        ]
        for key in done:
            del self.pairs[key]


async def record(
    venues: Venues,
    *,
    directory: str | Path = DEFAULT_SPORTS_DIR,
    hours: float | None = None,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    clock: Clock = time.time,
    sleep: Sleep = asyncio.sleep,
    log: Log = print,
) -> Counter[str]:
    """Record until ``hours`` pass (or the task is cancelled); the rows written.

    A cycle that fails (an HTTP error after retries) is counted and logged,
    and the next one runs at its time: a venue's bad minute loses one
    cycle, not the recording."""
    recorder = SportsRecorder(venues, SportsWriter(directory), clock=clock)
    end = None if hours is None else clock() + hours * 3600.0
    while end is None or clock() < end:
        started = clock()
        try:
            written = await recorder.cycle()
        except HttpError as exc:
            recorder.errors += 1
            log(f"cycle failed ({recorder.errors} so far): {exc}")
        else:
            recorder.retire(started)
            log(
                f"{len(recorder.pairs)} pairs, {written} quotes, "
                f"{recorder.ambiguous} ambiguous, {len(recorder.listed)} listings"
            )
        await sleep(max(0.0, interval - (clock() - started)))
    return recorder.writer.counts


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "DEFAULT_SPORTS_DIR",
    "KALSHI_SERIES",
    "MAX_START_GAP_SECONDS",
    "PM_LEAGUES",
    "RECORD_AFTER_START_SECONDS",
    "KalshiMatch",
    "KalshiSide",
    "Pair",
    "PmMatch",
    "SportsRecorder",
    "SportsWriter",
    "Venues",
    "kalshi_quote",
    "pair_up",
    "parse_kalshi",
    "parse_pm",
    "record",
    "same_side",
    "side_order",
    "side_words",
]
