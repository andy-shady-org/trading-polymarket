"""Candidate cross-venue pairs for a human to review (``pairs suggest``).

Reads Polymarket's busiest open events and Kalshi's open events, and scores
every Polymarket binary market against every Kalshi market by **title
similarity** (the Jaccard overlap of their normalised words, numbers kept, so
"above 4.25%" and "above 4.50%" differ) and **end-date proximity**. The top
matches go to a JSONL file; nothing is traded from it. A reviewer reads both
venues' rules for each candidate and approves the real ones with
``trading-polymarket pairs approve`` (docs/STRATEGIES.md): different
settlement sources, cut-off times or tie rules make two look-alike markets
different bets, and the ``crossvenue`` lane must never find that out with
money.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.kalshi import KalshiClient, KalshiMarket
from trading_polymarket.markets import Market

DEFAULT_SUGGESTIONS = "data/pairs_suggested.jsonl"
STOPWORDS = frozenset(
    "a an and are be before by de do does for from in is it its of on or the "
    "than this to vs what when which who will with yes no".split()
)
_WORD = re.compile(r"[a-z]+|\d+(?:\.\d+)?")


def words(text: str) -> frozenset[str]:
    """Lower-case words and numbers of ``text`` without stopwords."""
    return frozenset(w for w in _WORD.findall(text.lower()) if w not in STOPWORDS)


def kalshi_text(market: KalshiMarket) -> str:
    return f"{market.title} {market.yes_label}"


def pm_text(market: Market) -> str:
    parts = [market.question]
    if market.group_item_title and market.group_item_title not in market.question:
        parts.append(market.group_item_title)
    return " ".join(parts)


@dataclass(frozen=True)
class Suggestion:
    score: float
    similarity: float
    days_apart: float | None
    pm_question: str
    pm_token: str
    pm_end: float | None
    pm_ask: float | None
    kalshi_ticker: str
    kalshi_title: str
    kalshi_close: float | None
    kalshi_mid: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def suggest(
    pm_markets: Sequence[Market],
    kalshi_markets: Sequence[KalshiMarket],
    *,
    min_similarity: float = 0.5,
    max_days_apart: float = 3.0,
    per_market: int = 1,
) -> list[Suggestion]:
    """Ranked look-alikes; each Polymarket market keeps its ``per_market`` best.

    ``score`` is the similarity less 0.05 per day between the end dates (an
    unknown date costs nothing; a gap above ``max_days_apart`` drops the pair).
    """
    index: dict[str, list[int]] = defaultdict(list)
    k_words = [words(kalshi_text(m)) for m in kalshi_markets]
    for position, ws in enumerate(k_words):
        for word in ws:
            index[word].append(position)
    found: list[Suggestion] = []
    for market in pm_markets:
        if len(market.token_ids) != 2:
            continue
        mine = words(pm_text(market))
        shared: dict[int, int] = defaultdict(int)
        for word in mine:
            for position in index.get(word, ()):
                shared[position] += 1
        best = [
            s
            for position, count in shared.items()
            if (
                s := _suggestion(
                    market,
                    kalshi_markets[position],
                    count / len(mine | k_words[position]),
                    min_similarity,
                    max_days_apart,
                )
            )
            is not None
        ]
        best.sort(key=lambda s: s.score, reverse=True)
        found.extend(best[:per_market])
    found.sort(key=lambda s: s.score, reverse=True)
    return found


def _suggestion(
    market: Market,
    k_market: KalshiMarket,
    similarity: float,
    min_similarity: float,
    max_days_apart: float,
) -> Suggestion | None:
    if similarity < min_similarity:
        return None
    apart = _days_apart(market.end_time, k_market.close_time)
    if apart is not None and apart > max_days_apart:
        return None
    return Suggestion(
        score=round(similarity - 0.05 * (apart or 0.0), 4),
        similarity=round(similarity, 4),
        days_apart=None if apart is None else round(apart, 2),
        pm_question=pm_text(market),
        pm_token=market.yes_token,
        pm_end=market.end_time,
        pm_ask=market.best_ask,
        kalshi_ticker=k_market.ticker,
        kalshi_title=kalshi_text(k_market),
        kalshi_close=k_market.close_time,
        kalshi_mid=k_market.mid,
    )


def _days_apart(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return abs(a - b) / 86400.0


async def gather(
    gamma: GammaClient,
    kalshi: KalshiClient,
    *,
    pm_pages: int = 5,
    kalshi_pages: int = 10,
) -> tuple[list[Market], list[KalshiMarket]]:
    """Polymarket's busiest open markets and Kalshi's open markets."""
    pm: list[Market] = []
    for _, markets in await gamma.events(
        max_pages=pm_pages, closed=False, order="volume24hr", ascending=False
    ):
        pm.extend(m for m in markets if m.tradable)
    events = await kalshi.events(max_pages=kalshi_pages)
    return pm, [m for e in events for m in e.markets]


__all__ = [
    "DEFAULT_SUGGESTIONS",
    "Suggestion",
    "gather",
    "kalshi_text",
    "pm_text",
    "suggest",
    "words",
]
