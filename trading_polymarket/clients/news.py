"""Google News RSS: a free, keyless measure of attention on a topic.

``news.google.com/rss/search?q=...`` returns the latest matching headlines.
The module uses the *count of headlines in the last few hours* as an attention
metric for the trending lane (recorded with every entry so
``trading-core-audit cuts`` can test whether it predicts anything). X/Twitter
trends need a paid API and are deliberately not used (docs/DATA-SOURCES.md).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET  # nosec B405 - parsing a trusted public feed
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

from trading_polymarket.clients.http import JsonHttp, build_url

NEWS_URL = "https://news.google.com"


@dataclass(frozen=True)
class Headline:
    title: str
    published: float | None
    source: str = ""


def parse_rss(text: str) -> list[Headline]:
    try:
        root = ET.fromstring(text)  # noqa: S314 - public RSS, no entities used
    except ET.ParseError:
        return []
    found: list[Headline] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        raw_date = item.findtext("pubDate")
        published: float | None = None
        if raw_date:
            try:
                published = parsedate_to_datetime(raw_date).timestamp()
            except (TypeError, ValueError):
                published = None
        found.append(Headline(title, published, (item.findtext("source") or "")))
    return found


class NewsClient:
    def __init__(self, http: JsonHttp, *, base_url: str = NEWS_URL) -> None:
        self.http = http
        self.base_url = base_url

    async def headlines(self, query: str) -> list[Headline]:
        text = await self.http.get_text(
            build_url(
                self.base_url,
                "/rss/search",
                {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            )
        )
        return parse_rss(text)

    async def attention(self, query: str, *, now: float, hours: float = 6.0) -> int:
        """Headlines about ``query`` published in the last ``hours``."""
        cutoff = now - hours * 3600.0
        return sum(
            1
            for h in await self.headlines(query)
            if h.published is not None and h.published >= cutoff
        )


__all__ = ["Headline", "NewsClient", "parse_rss"]
