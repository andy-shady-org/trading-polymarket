"""Fed decisions on both venues: collect the history and replay the ``fed`` lane.

Collection (``trading-polymarket fed-history``) stores, per settled FOMC
meeting that both venues listed: every bucket the deterministic matcher
pairs (:func:`~trading_polymarket.pairs.match_fed`), its outcome on each
venue, Polymarket's hourly Yes price and Kalshi's hourly Yes bid/ask/volume
candles over the ``days`` before Kalshi's close (the statement).

Replay (``trading-polymarket backtest fed``) steps through each bucket hour
by hour, Yes and No side separately, with the live lane's rules and only
what was known at that hour: the last Kalshi candle that had closed, the
reference volume of the 24 h before, and Polymarket's last price plus a
modelled ``half_spread`` as the cost. One round trip per token and meeting;
it closes at convergence (Polymarket's modelled bid reaching Kalshi's mid,
when ``exit_on_convergence``) or at resolution.

Every replay also reports, for the hours before the close set by
``horizons``, the Brier scores of Polymarket's price (``market``), Kalshi's
mid (``model``) and their average (``blend``) on the bucket outcomes - the
question behind the lane: is Kalshi the better-informed price?
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.http import HttpError
from trading_polymarket.clients.kalshi import (
    STATUS_SETTLED,
    Candle,
    KalshiClient,
    KalshiEvent,
    KalshiMarket,
    candle_at,
)
from trading_polymarket.config import LANE_FED, ReferenceLane
from trading_polymarket.fees import FeeSchedule
from trading_polymarket.markets import Market, markets_from_event
from trading_polymarket.pairs import (
    FED_SERIES,
    SIDE_NO,
    SIDE_YES,
    Reference,
    VenuePair,
    fed_code_polymarket,
    is_fed_decision_event,
    match_fed,
)
from trading_polymarket.research.backtest import BacktestResult, brier_scores
from trading_polymarket.research.records import append_jsonl, read_jsonl, round_trip
from trading_polymarket.strategies.common import kelly_fraction, net_edge
from trading_polymarket.strategies.crossvenue import reference_fair, usable

DEFAULT_FED_HISTORY = "data/history/fed.jsonl"
HOUR = 3600.0
CHUNK_DAYS = 7  # Polymarket's prices-history refuses much longer windows
DEFAULT_HORIZONS = (168.0, 72.0, 24.0, 6.0, 1.0)
EXIT_CONVERGED = "converged"


@dataclass(frozen=True)
class FedBucket:
    bucket: str
    code: str
    yes_token: str
    no_token: str
    kalshi_ticker: str
    won: bool  # Polymarket's settlement
    kalshi_won: bool | None
    pm: tuple[tuple[float, float], ...]
    kalshi: tuple[Candle, ...]
    fee_rate: float = 0.0

    def pm_price(self, moment: float) -> float | None:
        price = None
        for t, p in self.pm:
            if t > moment:
                break
            price = p
        return price

    def reference_volume(self, moment: float, hours: float = 24.0) -> float:
        """Kalshi contracts traded in the ``hours`` up to ``moment``."""
        return sum(
            c.volume for c in self.kalshi if moment - hours * HOUR < c.t <= moment
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "code": self.code,
            "yes_token": self.yes_token,
            "no_token": self.no_token,
            "kalshi_ticker": self.kalshi_ticker,
            "won": self.won,
            "kalshi_won": self.kalshi_won,
            "fee_rate": self.fee_rate,
            "pm": [[round(t), round(p, 5)] for t, p in self.pm],
            "kalshi": [
                [round(c.t), c.yes_bid, c.yes_ask, c.volume] for c in self.kalshi
            ],
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> FedBucket:
        kalshi_won = row.get("kalshi_won")
        return cls(
            bucket=str(row["bucket"]),
            code=str(row["code"]),
            yes_token=str(row["yes_token"]),
            no_token=str(row["no_token"]),
            kalshi_ticker=str(row["kalshi_ticker"]),
            won=bool(row["won"]),
            kalshi_won=None if kalshi_won is None else bool(kalshi_won),
            fee_rate=float(row.get("fee_rate") or 0.0),
            pm=tuple((float(t), float(p)) for t, p in row["pm"]),
            kalshi=tuple(
                Candle(float(t), bid, ask, float(volume or 0.0))
                for t, bid, ask, volume in row["kalshi"]
            ),
        )


@dataclass(frozen=True)
class FedMeeting:
    event_id: str
    title: str
    kalshi_event: str
    close_time: float  # Kalshi's close: trading stops before the statement
    buckets: tuple[FedBucket, ...] = field(default=())

    @property
    def agreed(self) -> bool:
        """Did both venues settle every bucket the same way?"""
        return all(b.kalshi_won is None or b.kalshi_won == b.won for b in self.buckets)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "kalshi_event": self.kalshi_event,
            "close_time": self.close_time,
            "buckets": [b.to_dict() for b in self.buckets],
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> FedMeeting:
        return cls(
            event_id=str(row["event_id"]),
            title=str(row["title"]),
            kalshi_event=str(row["kalshi_event"]),
            close_time=float(row["close_time"]),
            buckets=tuple(FedBucket.from_dict(b) for b in row["buckets"]),
        )


def load_meetings(path: str | Path = DEFAULT_FED_HISTORY) -> list[FedMeeting]:
    return [FedMeeting.from_dict(row) for row in read_jsonl(path)]


# -- collection ---------------------------------------------------------------
async def settled_fed_events(
    kalshi: KalshiClient, *, max_pages: int = 3
) -> tuple[list[KalshiEvent], set[str]]:
    """Kalshi's settled Fed events with markets; the set names archived ones."""
    events = await kalshi.events(
        series_ticker=FED_SERIES, status=STATUS_SETTLED, max_pages=max_pages
    )
    archived: set[str] = set()
    out: list[KalshiEvent] = []
    for event in events:
        if not event.markets:
            markets = await kalshi.historical_markets(event.event_ticker)
            if not markets:
                continue
            archived.add(event.event_ticker)
            event = replace(event, markets=tuple(markets))
        out.append(event)
    return out, archived


async def _pm_series(
    clob: ClobClient, token: str, start: float, end: float
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    low = start
    while low < end:
        high = min(end, low + CHUNK_DAYS * 86400.0)
        points.extend(
            (p.t, p.p) for p in await clob.prices_history(token, start=low, end=high)
        )
        low = high
    unique = dict(points)
    return sorted(unique.items())


async def _kalshi_series(
    kalshi: KalshiClient, ticker: str, start: float, end: float, archived: bool
) -> list[Candle]:
    try:
        return await kalshi.candlesticks(
            FED_SERIES, ticker, start=start, end=end, historical=archived
        )
    except HttpError as exc:
        if archived or exc.status != 404:
            raise
        # Archived since the event list was read: ask the historical endpoint.
        return await kalshi.candlesticks(
            FED_SERIES, ticker, start=start, end=end, historical=True
        )


async def _bucket(
    clob: ClobClient,
    kalshi: KalshiClient,
    gate: asyncio.Semaphore,
    pair: VenuePair,
    market: Market,
    k_market: KalshiMarket,
    window: tuple[float, float],
    archived: bool,
) -> FedBucket:
    start, close = window
    async with gate:
        pm = await _pm_series(clob, pair.pm_token, start, close)
        candles = await _kalshi_series(
            kalshi, pair.kalshi_ticker, start, close, archived
        )
    return FedBucket(
        bucket=market.group_item_title,
        code=str(fed_code_polymarket(market.group_item_title)),
        yes_token=market.yes_token,
        no_token=market.no_token,
        kalshi_ticker=pair.kalshi_ticker,
        won=market.payout(market.yes_token) == 1.0,
        kalshi_won=k_market.settled_yes,
        pm=tuple(pm),
        kalshi=tuple(candles),
        fee_rate=market.fee.rate,
    )


async def collect_fed(
    gamma: GammaClient,
    clob: ClobClient,
    kalshi: KalshiClient,
    *,
    path: str | Path = DEFAULT_FED_HISTORY,
    days: float = 14.0,
    query: str = "Fed Decision in",
    concurrency: int = 4,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Append settled meetings not yet in ``path``; returns how many."""
    seen = {str(r.get("event_id")) for r in read_jsonl(path)}
    raw_events = await gamma.search_events(query, status="closed", limit=100)
    pm_events = [
        (raw, markets_from_event(raw, default_fee_rate=gamma.default_fee_rate))
        for raw in raw_events
        if is_fed_decision_event(str(raw.get("title") or ""))
        and str(raw.get("id")) not in seen
    ]
    kalshi_events, archived = await settled_fed_events(kalshi)
    gate = asyncio.Semaphore(concurrency)
    written = 0
    for raw, markets in pm_events:
        title = str(raw.get("title"))
        try:
            meeting = await _meeting(
                raw, markets, kalshi_events, archived, clob, kalshi, gate, days
            )
        except HttpError as exc:  # skip the meeting, keep collecting
            _say(progress, f"{title}: {exc}")
            continue
        if meeting is None:
            continue
        if not meeting.buckets:
            _say(progress, f"{title}: no Kalshi meeting matched")
            continue
        written += append_jsonl(path, [meeting.to_dict()])
        _say(
            progress,
            f"{title} ({meeting.kalshi_event}): {len(meeting.buckets)} buckets",
        )
    return written


def _say(progress: Callable[[str], None] | None, text: str) -> None:
    if progress is not None:
        progress(text)


async def _meeting(
    raw: Mapping[str, Any],
    markets: Sequence[Market],
    kalshi_events: Sequence[KalshiEvent],
    archived: set[str],
    clob: ClobClient,
    kalshi: KalshiClient,
    gate: asyncio.Semaphore,
    days: float,
) -> FedMeeting | None:
    """One settled meeting (no buckets: nothing matched; ``None``: unsettled)."""
    if not markets or not all(m.resolved for m in markets):
        return None
    pairs = [
        p
        for p in match_fed([(raw, markets)], kalshi_events)
        if p.kalshi_side == SIDE_YES
    ]
    if not pairs:
        return FedMeeting(str(raw.get("id")), str(raw.get("title")), "", 0.0)
    by_ticker = {m.ticker: (e, m) for e in kalshi_events for m in e.markets}
    by_token = {m.yes_token: m for m in markets}
    event, _ = by_ticker[pairs[0].kalshi_ticker]
    close = min(m.close_time for m in event.markets if m.close_time is not None)
    buckets = await asyncio.gather(
        *(
            _bucket(
                clob,
                kalshi,
                gate,
                pair,
                by_token[pair.pm_token],
                by_ticker[pair.kalshi_ticker][1],
                (close - days * 86400.0, close),
                event.event_ticker in archived,
            )
            for pair in pairs
        )
    )
    return FedMeeting(
        event_id=str(raw.get("id")),
        title=str(raw.get("title")),
        kalshi_event=event.event_ticker,
        close_time=close,
        buckets=tuple(buckets),
    )


# -- replay -------------------------------------------------------------------
def _side_reference(candle: Candle, side: str, volume: float) -> Reference:
    if side == SIDE_YES:
        bid, ask = candle.yes_bid, candle.yes_ask
    else:
        bid = None if candle.yes_ask is None else round(1.0 - candle.yes_ask, 6)
        ask = None if candle.yes_bid is None else round(1.0 - candle.yes_bid, 6)
    return Reference(bid, ask, volume, candle.t)


@dataclass(frozen=True)
class _Entry:
    time: float
    cost: float
    notional: float
    fee: float
    reference: Reference


def _hours(
    meeting: FedMeeting, bucket: FedBucket, side: str
) -> Iterator[tuple[float, float, Reference]]:
    """``(hour, side's Polymarket price, Kalshi reference)`` up to the close."""
    for candle in bucket.kalshi:
        if candle.t > meeting.close_time:
            return
        yes = bucket.pm_price(candle.t)
        if yes is None:
            continue
        price = yes if side == SIDE_YES else 1.0 - yes
        volume = bucket.reference_volume(candle.t)
        yield candle.t, price, _side_reference(candle, side, volume)


def _entry(
    moment: float,
    price: float,
    reference: Reference,
    lane: ReferenceLane,
    fee: FeeSchedule,
    bankroll: float,
    half_spread: float,
) -> _Entry | None:
    """The live lane's buy decision at one hour (``None``: no buy)."""
    fair = reference_fair(reference, lane)
    cost = min(0.999, price + half_spread)
    if usable(reference, lane, moment) is not None or fair is None:
        return None
    if not lane.min_price <= cost <= lane.max_price:
        return None
    if not lane.min_edge <= net_edge(fair, cost, fee) <= lane.max_edge:
        return None
    kelly = kelly_fraction(fair, cost + fee.per_share(cost))
    notional = min(lane.max_notional, lane.kelly_fraction * kelly * bankroll)
    if notional < lane.min_notional:
        return None
    entry_fee = round(notional / cost * fee.per_share(cost), 5)
    return _Entry(moment, cost, notional, entry_fee, reference)


def _converged_bid(
    price: float, reference: Reference, lane: ReferenceLane, half_spread: float
) -> float | None:
    """The modelled bid when it has reached the Kalshi mid (sell), else ``None``."""
    bid = max(0.001, price - half_spread)
    mid = reference.mid
    if not lane.exit_on_convergence or mid is None:
        return None
    return bid if bid >= mid - lane.convergence_margin else None


def _trade_side(
    meeting: FedMeeting,
    bucket: FedBucket,
    side: str,
    lane: ReferenceLane,
    bankroll: float,
    half_spread: float,
) -> tuple[list[dict[str, Any]], float]:
    token = bucket.yes_token if side == SIDE_YES else bucket.no_token
    won = bucket.won if side == SIDE_YES else not bucket.won
    fee = FeeSchedule(rate=bucket.fee_rate)
    last_entry = meeting.close_time - lane.min_hours * HOUR
    entry: _Entry | None = None
    for moment, price, reference in _hours(meeting, bucket, side):
        if entry is None:
            if moment <= last_entry:
                entry = _entry(
                    moment, price, reference, lane, fee, bankroll, half_spread
                )
            continue
        bid = _converged_bid(price, reference, lane, half_spread)
        if bid is not None:
            return _round_trip(
                meeting, bucket, side, token, entry, moment, bid, fee, EXIT_CONVERGED
            )
    if entry is None:
        return [], 0.0
    payout = 1.0 if won else 0.0
    return _round_trip(
        meeting, bucket, side, token, entry, meeting.close_time, payout, fee, "resolved"
    )


def _round_trip(
    meeting: FedMeeting,
    bucket: FedBucket,
    side: str,
    token: str,
    entry: _Entry,
    exit_time: float,
    exit_price: float,
    fee: FeeSchedule,
    reason: str,
) -> tuple[list[dict[str, Any]], float]:
    moment, cost, notional = entry.time, entry.cost, entry.notional
    entry_fee, reference = entry.fee, entry.reference
    size = notional / cost
    exit_fee = (
        0.0 if reason == "resolved" else round(size * fee.per_share(exit_price), 5)
    )
    name = f"{meeting.title.rstrip('?')} {bucket.bucket}" + (
        " (No)" if side == SIDE_NO else ""
    )
    records = round_trip(
        instrument_id=token,
        name=name,
        strategy=LANE_FED,
        reason=f"backtest fed Kalshi {reference.mid or 0:.3f} vs {cost:.3f}",
        entry_time=moment,
        entry_price=cost,
        notional=notional,
        entry_fee=entry_fee,
        exit_time=exit_time,
        exit_price=exit_price,
        exit_fee=exit_fee,
        exit_reason=reason,
        metrics={
            "fair": round(reference.mid or 0.0, 4),
            "kalshi_bid": reference.bid,
            "kalshi_ask": reference.ask,
            "kalshi_volume_24h": round(reference.volume_24h, 1),
            "kalshi_ticker": bucket.kalshi_ticker,
            "kalshi_side": side,
        },
    )
    return records, size * exit_price - notional - entry_fee - exit_fee


def score_horizons(
    meetings: Sequence[FedMeeting], horizons: Sequence[float] = DEFAULT_HORIZONS
) -> dict[str, Any]:
    """Brier scores of Polymarket vs Kalshi ``hours`` before each close."""
    out: dict[str, Any] = {}
    for hours in horizons:
        rows: list[tuple[float, float, float, bool]] = []
        for meeting in meetings:
            moment = meeting.close_time - hours * HOUR
            for bucket in meeting.buckets:
                pm = bucket.pm_price(moment)
                candle = candle_at(bucket.kalshi, moment)
                if pm is None or candle is None or candle.mid is None:
                    continue
                rows.append((candle.mid, pm, (candle.mid + pm) / 2.0, bucket.won))
        scores = brier_scores(rows)
        if scores:
            scores["mean_abs_gap"] = round(
                sum(abs(model - market) for model, market, _, _ in rows) / len(rows), 5
            )
            out[f"{hours:g}h"] = scores
    return out


def backtest_fed(
    meetings: Sequence[FedMeeting],
    lane: ReferenceLane,
    *,
    bankroll: float = 1000.0,
    half_spread: float = 0.01,
    horizons: Sequence[float] = DEFAULT_HORIZONS,
) -> BacktestResult:
    """Replay the ``fed`` lane; see the module docstring.

    A meeting the two venues settled differently is skipped (and counted in
    ``disagreements``): the pair was not the same question.
    """
    records: list[dict[str, Any]] = []
    trades = 0
    net = 0.0
    used = [m for m in meetings if m.agreed]
    for meeting in sorted(used, key=lambda m: m.close_time):
        for bucket in meeting.buckets:
            for side in (SIDE_YES, SIDE_NO):
                added, pnl = _trade_side(
                    meeting, bucket, side, lane, bankroll, half_spread
                )
                records.extend(added)
                trades += len(added) // 2
                net += pnl
    scores = score_horizons(used, horizons)
    if len(used) != len(meetings):
        scores["disagreements"] = len(meetings) - len(used)
    return BacktestResult(records, trades, len(used), round(net, 4), scores=scores)


__all__ = [
    "DEFAULT_FED_HISTORY",
    "DEFAULT_HORIZONS",
    "FedBucket",
    "FedMeeting",
    "backtest_fed",
    "collect_fed",
    "load_meetings",
    "score_horizons",
    "settled_fed_events",
]
