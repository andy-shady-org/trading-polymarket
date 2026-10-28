from __future__ import annotations

from trading_polymarket.clients.news import Headline, NewsClient, parse_rss
from trading_polymarket.tests.support.factories import NOW
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http

RSS = """<?xml version="1.0"?><rss><channel>
<item><title> Fresh </title><pubDate>Wed, 28 Oct 2026 11:00:00 GMT</pubDate>
<source>Wire</source></item>
<item><title>Old</title><pubDate>Mon, 26 Oct 2026 11:00:00 GMT</pubDate></item>
<item><title>Undated</title></item>
<item><title>Bad date</title><pubDate>whenever</pubDate></item>
</channel></rss>"""


def test_parse_rss() -> None:
    items = parse_rss(RSS)
    assert items[0] == Headline("Fresh", NOW - 3600, "Wire")
    assert items[2].published is None and items[3].published is None
    assert parse_rss("<not xml") == []


async def test_attention_counts_recent_headlines() -> None:
    transport = FakeTransport({"/rss/search": RSS})
    news = NewsClient(fake_http(transport), base_url="https://n.test")
    assert await news.attention("election", now=NOW, hours=6) == 1
    assert "q=election" in transport.calls[0]
