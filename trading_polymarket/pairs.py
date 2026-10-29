"""The same question on two venues: Polymarket tokens paired with Kalshi markets.

A :class:`VenuePair` says "this Polymarket token pays 1 exactly when this
Kalshi market's ``side`` (``yes`` or ``no``) pays 1". Pairs come from:

* :func:`match_fed` - deterministic: Polymarket's "Fed Decision in <Month>?"
  buckets against Kalshi's ``KXFEDDECISION-<YY><MON>`` markets for the same
  meeting (same date, same move: ``No change`` = ``Fed maintains rate``,
  ``25 bps decrease`` = ``Cut 25bps``, ``50+ bps decrease`` = ``Cut >25bps``,
  ...); both venues round an off-grid move up to the next 25 bps;
* a **reviewed pairs file** (``data/pairs.json``) for everything else:
  ``trading-polymarket pairs suggest`` proposes candidates by title and date,
  a human checks both venues' rules, and ``pairs approve`` writes the ones
  that really are the same question. Nothing fuzzy is ever traded unreviewed.

:class:`Reference` turns a Kalshi quote into a bid/ask/mid for the paired
Polymarket token (a ``no`` side is ``1 - yes``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_polymarket.clients.kalshi import KalshiEvent, KalshiMarket
from trading_polymarket.markets import Market

SIDE_YES = "yes"
SIDE_NO = "no"
SOURCE_FED = "fed"
SOURCE_APPROVED = "approved"
FED_SERIES = "KXFEDDECISION"
MAX_MEETING_GAP_SECONDS = 3 * 86400.0

_PM_MOVE = re.compile(r"(\d+)\s*(\+)?\s*bps\s*(decrease|increase)", re.I)
_KALSHI_MOVE = re.compile(r"(cut|hike)\s*(>)?\s*(\d+)\s*bps", re.I)
_PM_FED_TITLE = re.compile(r"^Fed Decision in ([A-Za-z]+)\??$", re.I)


@dataclass(frozen=True)
class VenuePair:
    pm_token: str
    kalshi_ticker: str
    kalshi_side: str = SIDE_YES
    kalshi_series: str = ""
    label: str = ""
    source: str = SOURCE_APPROVED

    def __post_init__(self) -> None:
        if self.kalshi_side not in (SIDE_YES, SIDE_NO):
            raise ValueError("kalshi_side must be 'yes' or 'no'")
        if not self.pm_token or not self.kalshi_ticker:
            raise ValueError("a pair needs a Polymarket token and a Kalshi ticker")

    @property
    def series(self) -> str:
        """Kalshi series ticker (``KXFEDDECISION`` from ``KXFEDDECISION-26DEC-H0``)."""
        return self.kalshi_series or self.kalshi_ticker.split("-", 1)[0]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> VenuePair:
        return cls(
            pm_token=str(data["pm_token"]),
            kalshi_ticker=str(data["kalshi_ticker"]),
            kalshi_side=str(data.get("kalshi_side") or SIDE_YES),
            kalshi_series=str(data.get("kalshi_series") or ""),
            label=str(data.get("label") or ""),
            source=str(data.get("source") or SOURCE_APPROVED),
        )


@dataclass(frozen=True)
class Reference:
    """Kalshi's quote, seen from the paired Polymarket token."""

    bid: float | None
    ask: float | None
    volume_24h: float
    timestamp: float

    @classmethod
    def of(cls, market: KalshiMarket, side: str, timestamp: float) -> Reference:
        if side == SIDE_YES:
            bid, ask = market.yes_bid, market.yes_ask
        else:
            bid = None if market.yes_ask is None else round(1.0 - market.yes_ask, 6)
            ask = None if market.yes_bid is None else round(1.0 - market.yes_bid, 6)
        return cls(bid, ask, market.volume_24h, timestamp)

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid


# -- Fed decision mapping ----------------------------------------------------
def fed_code_polymarket(label: str) -> str | None:
    """``H0`` / ``C25`` / ``C26`` / ``H25`` / ``H26`` from a Polymarket bucket."""
    text = label.strip().lower()
    if text in ("no change", "no change in rates"):
        return "H0"
    match = _PM_MOVE.search(text)
    if match is None:
        return None
    size, plus, direction = int(match[1]), bool(match[2]), match[3].lower()
    prefix = "C" if direction == "decrease" else "H"
    if size == 25 and not plus:
        return f"{prefix}25"
    if size == 50 and plus:
        return f"{prefix}26"  # "50+ bps" = "more than 25 bps"
    return None


def fed_code_kalshi(label: str) -> str | None:
    """The same codes from a Kalshi ``yes_sub_title``."""
    text = label.strip().lower()
    if "maintain" in text or text == "no change":  # older events: "No change"
        return "H0"
    match = _KALSHI_MOVE.search(text)
    if match is None:
        return None
    direction, more, size = match[1].lower(), bool(match[2]), int(match[3])
    if size != 25:
        return None
    prefix = "C" if direction == "cut" else "H"
    return f"{prefix}26" if more else f"{prefix}25"


def is_fed_decision_event(title: str) -> bool:
    return _PM_FED_TITLE.match(title.strip()) is not None


def _meeting_time(markets: Iterable[Market]) -> float | None:
    times = [m.end_time for m in markets if m.end_time is not None]
    return min(times) if times else None


def match_fed(
    pm_events: Sequence[tuple[Mapping[str, Any], Sequence[Market]]],
    kalshi_events: Sequence[KalshiEvent],
) -> list[VenuePair]:
    """Pair every mapped bucket of each Polymarket Fed meeting with Kalshi's."""
    pairs: list[VenuePair] = []
    for raw, markets in pm_events:
        if not is_fed_decision_event(str(raw.get("title") or "")):
            continue
        meeting = _meeting_time(markets)
        if meeting is None:
            continue
        kalshi = _closest_event(kalshi_events, meeting)
        if kalshi is None:
            continue
        by_code = {
            code: m
            for m in kalshi.markets
            if (code := fed_code_kalshi(m.yes_label)) is not None
        }
        for market in markets:
            code = fed_code_polymarket(market.group_item_title)
            target = by_code.get(code) if code else None
            if target is None or len(market.token_ids) != 2:
                continue
            month = f"{datetime.fromtimestamp(meeting, UTC):%b %Y}"
            label = f"Fed {month} {market.group_item_title}"
            pairs.append(
                VenuePair(
                    market.yes_token,
                    target.ticker,
                    SIDE_YES,
                    FED_SERIES,
                    label,
                    SOURCE_FED,
                )
            )
            pairs.append(
                VenuePair(
                    market.no_token,
                    target.ticker,
                    SIDE_NO,
                    FED_SERIES,
                    f"{label} (No)",
                    SOURCE_FED,
                )
            )
    return pairs


def _closest_event(events: Sequence[KalshiEvent], moment: float) -> KalshiEvent | None:
    best: tuple[float, KalshiEvent] | None = None
    for event in events:
        closes = [m.close_time for m in event.markets if m.close_time is not None]
        if not closes:
            continue
        gap = abs(min(closes) - moment)
        if gap <= MAX_MEETING_GAP_SECONDS and (best is None or gap < best[0]):
            best = (gap, event)
    return best[1] if best else None


# -- reviewed pairs file -----------------------------------------------------
def load_pairs(path: str | Path) -> list[VenuePair]:
    """Approved pairs from ``path`` (missing file: none; bad entries skipped)."""
    target = Path(path)
    if not target.is_file():
        return []
    rows = json.loads(target.read_text())
    pairs = []
    for row in rows if isinstance(rows, list) else []:
        try:
            pairs.append(VenuePair.from_dict(row))
        except (KeyError, TypeError, ValueError):
            continue
    return pairs


def save_pairs(pairs: Iterable[VenuePair], path: str | Path) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    unique = {(p.pm_token, p.kalshi_ticker, p.kalshi_side): p for p in pairs}
    target.write_text(
        json.dumps([p.to_dict() for p in unique.values()], indent=1) + "\n"
    )
    return str(target)


__all__ = [
    "FED_SERIES",
    "SIDE_NO",
    "SIDE_YES",
    "SOURCE_APPROVED",
    "SOURCE_FED",
    "Reference",
    "VenuePair",
    "fed_code_kalshi",
    "fed_code_polymarket",
    "is_fed_decision_event",
    "load_pairs",
    "match_fed",
    "save_pairs",
]
