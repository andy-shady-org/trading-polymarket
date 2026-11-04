"""Which markets pay liquidity rewards, on what terms, against whom (FEAT-153).

``trading-polymarket rewards-scan`` reads every market paying liquidity
rewards today (CLOB ``/rewards/markets/current``), takes the ``--limit``
best paid, and for each reads its details (Gamma) and its book (the first
outcome's ``/book``). It writes one JSON line a market and prints them
ranked by the estimated reward per dollar a quote ties up. Record-only.

**Polymarket's scoring** (docs.polymarket.com, "Liquidity rewards"): an order
``s`` cents from the midpoint, in a market whose reward spread is ``v``
cents, scores ``((v − s) / v)² × size``, and nothing at ``s ≥ v`` or below
the market's minimum size. One side is the bids on the first outcome (and
asks on the second), the other the asks on the first (bids on the second).
With the midpoint in [0.10, 0.90] a maker scores
``max(min(one, two), max(one, two) / 3)``; outside it, ``min(one, two)``:
both sides or nothing. The book is sampled once a minute and a maker's
share of the day's pool is its share of the scores.

**The estimate is one snapshot, not a sampled day.** The book is scored as
if all of it were one maker (real makers score more when one-sided, less
when two-sided), every resting share inside the spread is counted (orders
below the minimum size do not score, so this overstates the competition),
and a quote is assumed to sit there all day. It ignores adverse selection:
what a maker loses to better-informed takers, which FEAT-101's maker study
measures. It ranks where to look, not what a quote would earn.

**Flags.** A market past its end date (most often an election awaiting its
result) is ``ended``: its quotes face takers who know the outcome. A book
whose best bid and ask are more than twice the reward spread apart is a
``wide book``: its midpoint means little (a 1 c bid and a 99 c ask make a
0.50 midpoint with nobody near it). Both are kept in the file but ranked
after every clean book.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_polymarket.book import Level, OrderBook
from trading_polymarket.clients.clob import BookUnavailable, ClobClient
from trading_polymarket.clients.gamma import GammaClient

DEFAULT_REWARDS_DIR = "data/rewards"
DEFAULT_LIMIT = 200
TWO_SIDED_BELOW = 0.10
TWO_SIDED_ABOVE = 0.90
ONE_SIDED_DIVISOR = 3.0  # Polymarket's c
CENT = 0.01

Progress = Callable[[str], None]


@dataclass(frozen=True)
class RewardTerms:
    """A market's reward terms today (CLOB ``/rewards/markets/current``)."""

    condition_id: str
    daily_rate: float
    min_size: float
    max_spread_cents: float

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> RewardTerms | None:
        """A row, or ``None`` when it is malformed or pays nothing."""
        try:
            rate = _daily_rate(raw)
            terms = cls(
                condition_id=str(raw["condition_id"]),
                daily_rate=rate,
                min_size=float(raw["rewards_min_size"]),
                max_spread_cents=float(raw["rewards_max_spread"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if not terms.condition_id or rate <= 0 or terms.max_spread_cents <= 0:
            return None
        return terms


def _daily_rate(raw: Mapping[str, Any]) -> float:
    """``total_daily_rate``, or the sum of the configs' ``rate_per_day``."""
    total = raw.get("total_daily_rate")
    if total is not None:
        return float(total)
    configs = raw.get("rewards_config") or []
    return float(sum(float(c.get("rate_per_day") or 0) for c in configs))


def parse_terms(rows: Sequence[Mapping[str, Any]]) -> list[RewardTerms]:
    parsed = (RewardTerms.from_api(r) for r in rows)
    return [t for t in parsed if t is not None]


def order_score(distance_cents: float, size: float, spread_cents: float) -> float:
    """Polymarket's ``((v − s) / v)² × size``; 0 at or beyond the spread."""
    if distance_cents >= spread_cents or size <= 0:
        return 0.0
    return ((spread_cents - distance_cents) / spread_cents) ** 2 * size


def side_score(levels: Sequence[Level], mid: float, spread_cents: float) -> float:
    """The score of every resting share on one side of the book."""
    return float(
        sum(
            order_score(abs(level.price - mid) / CENT, level.size, spread_cents)
            for level in levels
        )
    )


def maker_score(one: float, two: float, mid: float) -> float:
    """A maker's score from its two sides, under the two-sided rule."""
    if mid < TWO_SIDED_BELOW or mid > TWO_SIDED_ABOVE:
        return min(one, two)
    return max(min(one, two), max(one, two) / ONE_SIDED_DIVISOR)


def shares_within(levels: Sequence[Level], mid: float, spread_cents: float) -> float:
    return float(
        sum(lv.size for lv in levels if abs(lv.price - mid) / CENT < spread_cents)
    )


@dataclass(frozen=True)
class Quote:
    """The quote to estimate: ``shares`` each side, ``cents`` from the midpoint."""

    shares: float | None = None  # None: the market's minimum size
    cents: float = 1.0


@dataclass(frozen=True)
class Scan:
    """One market's row."""

    condition_id: str
    question: str
    slug: str
    tokens: tuple[str, ...]
    daily_rate: float
    min_size: float
    max_spread_cents: float
    gamma_min_size: float | None
    gamma_max_spread: float | None
    best_bid: float | None
    best_ask: float | None
    mid: float | None
    shares_bid: float
    shares_ask: float
    competition_score: float
    quote_shares: float
    quote_cents: float
    reward_two_sided: float
    reward_one_sided: float
    capital: float
    reward_per_dollar: float
    volume_24h: float
    hours_to_end: float | None
    fee_rate: float
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["tokens"] = list(self.tokens)
        return row


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tokens(raw: Mapping[str, Any]) -> tuple[str, ...]:
    value = raw.get("clobTokenIds")
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return ()
    return tuple(str(t) for t in parsed) if isinstance(parsed, list) else ()


def _hours_to_end(raw: Mapping[str, Any], now: float) -> float | None:
    try:
        end = datetime.fromisoformat(str(raw["endDate"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None
    return round((end.timestamp() - now) / 3600, 1)


def _fee_rate(raw: Mapping[str, Any]) -> float:
    schedule = raw.get("feeSchedule")
    rate = schedule.get("rate") if isinstance(schedule, Mapping) else None
    return _number(rate) or 0.0


@dataclass(frozen=True)
class _Estimate:
    competition: float
    two_sided: float
    one_sided: float
    capital: float


def estimate(book: OrderBook, terms: RewardTerms, quote: Quote) -> _Estimate:
    """Our share of the pool for ``quote`` against this book (see the docstring)."""
    mid = book.mid
    assert mid is not None
    v = terms.max_spread_cents
    competition = maker_score(
        side_score(book.bids, mid, v), side_score(book.asks, mid, v), mid
    )
    shares = terms.min_size if quote.shares is None else quote.shares
    ours = order_score(quote.cents, shares, v) if shares >= terms.min_size else 0.0
    two = maker_score(ours, ours, mid)
    one = maker_score(ours, 0.0, mid)
    capital = shares * max(0.0, 1.0 - 2.0 * quote.cents * CENT)
    return _Estimate(
        competition=competition,
        two_sided=_share(two, competition) * terms.daily_rate,
        one_sided=_share(one, competition) * terms.daily_rate,
        capital=capital,
    )


def _share(ours: float, competition: float) -> float:
    return ours / (ours + competition) if ours > 0 else 0.0


def _note(book: OrderBook, terms: RewardTerms, hours: float | None) -> str:
    """Why a clean-looking estimate cannot be trusted ('' when it can)."""
    notes = []
    if hours is not None and hours < 0:
        notes.append("ended")
    spread = book.spread
    if spread is not None and spread > 2 * terms.max_spread_cents * CENT:
        notes.append("wide book")
    return ", ".join(notes)


def scan_row(
    terms: RewardTerms,
    raw: Mapping[str, Any],
    book: OrderBook | None,
    quote: Quote,
    now: float,
) -> Scan:
    """One market's row; a market without a two-sided book gets a note."""
    shares = terms.min_size if quote.shares is None else quote.shares
    common: dict[str, Any] = {
        "condition_id": terms.condition_id,
        "question": str(raw.get("question") or ""),
        "slug": str(raw.get("slug") or ""),
        "tokens": _tokens(raw),
        "daily_rate": terms.daily_rate,
        "min_size": terms.min_size,
        "max_spread_cents": terms.max_spread_cents,
        "gamma_min_size": _number(raw.get("rewardsMinSize")),
        "gamma_max_spread": _number(raw.get("rewardsMaxSpread")),
        "quote_shares": shares,
        "quote_cents": quote.cents,
        "volume_24h": _number(raw.get("volume24hr")) or 0.0,
        "hours_to_end": _hours_to_end(raw, now),
        "fee_rate": _fee_rate(raw),
    }
    if book is None or book.mid is None:
        return Scan(
            **common,
            best_bid=None if book is None else book.best_bid,
            best_ask=None if book is None else book.best_ask,
            mid=None,
            shares_bid=0.0,
            shares_ask=0.0,
            competition_score=0.0,
            reward_two_sided=0.0,
            reward_one_sided=0.0,
            capital=0.0,
            reward_per_dollar=0.0,
            note="no book" if book is None else "one-sided book",
        )
    found = estimate(book, terms, quote)
    v, mid = terms.max_spread_cents, book.mid
    return Scan(
        **common,
        note=_note(book, terms, common["hours_to_end"]),
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        mid=mid,
        shares_bid=shares_within(book.bids, mid, v),
        shares_ask=shares_within(book.asks, mid, v),
        competition_score=round(found.competition, 2),
        reward_two_sided=round(found.two_sided, 4),
        reward_one_sided=round(found.one_sided, 4),
        capital=round(found.capital, 2),
        reward_per_dollar=(
            round(found.two_sided / found.capital, 5) if found.capital else 0.0
        ),
    )


async def _book(clob: ClobClient, tokens: Sequence[str]) -> OrderBook | None:
    if not tokens:
        return None
    try:
        return await clob.book(tokens[0])
    except BookUnavailable:
        return None


def _quiet(_: str) -> None:
    return None


async def scan(
    clob: ClobClient,
    gamma: GammaClient,
    *,
    limit: int = DEFAULT_LIMIT,
    min_daily_rate: float = 0.0,
    quote: Quote = Quote(),
    now: float | None = None,
    progress: Progress | None = None,
) -> tuple[int, list[Scan]]:
    """(markets paying rewards, the ``limit`` best paid, scanned and ranked)."""
    say = progress or _quiet
    every = parse_terms(await clob.rewards_markets())
    chosen = sorted(
        (t for t in every if t.daily_rate >= min_daily_rate),
        key=lambda t: t.daily_rate,
        reverse=True,
    )[:limit]
    say(f"{len(every)} markets pay rewards; scanning the {len(chosen)} best paid")
    details = await gamma.raw_markets_by_condition_ids([t.condition_id for t in chosen])
    by_id = {str(r.get("conditionId") or ""): r for r in details}
    moment = time.time() if now is None else now
    rows: list[Scan] = []
    for terms in chosen:
        raw = by_id.get(terms.condition_id, {})
        book = await _book(clob, _tokens(raw))
        rows.append(scan_row(terms, raw, book, quote, moment))
    rows.sort(key=lambda r: (r.note == "", r.reward_per_dollar), reverse=True)
    return len(every), rows


def write_rows(rows: Sequence[Scan], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_dict(), separators=(",", ":")) + "\n")
    return target


def default_out(now: float) -> str:
    stamp = datetime.fromtimestamp(now, UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{DEFAULT_REWARDS_DIR}/rewards-{stamp}.jsonl"


__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_REWARDS_DIR",
    "Quote",
    "RewardTerms",
    "Scan",
    "default_out",
    "estimate",
    "maker_score",
    "order_score",
    "parse_terms",
    "scan",
    "scan_row",
    "shares_within",
    "side_score",
    "write_rows",
]
