from __future__ import annotations

from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.kalshi import KalshiClient, KalshiMarket
from trading_polymarket.research import pairs_suggest as ps
from trading_polymarket.tests.support.factories import (
    NOW,
    gamma_market,
    iso,
    kalshi_market,
    market,
)
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http


def k(
    title: str, subtitle: str = "", close: float | None = NOW, **kw: object
) -> KalshiMarket:
    return KalshiMarket.from_api(
        kalshi_market(
            kw.pop("ticker", "K-1"),  # type: ignore[arg-type]
            title=title,
            yes_sub_title=subtitle,
            close_time=None if close is None else iso(close),
            **kw,
        )
    )


def test_words_drop_stopwords_and_keep_numbers() -> None:
    assert ps.words("Will the Fed cut rates by 0.25 in 2026?") == {
        "fed",
        "cut",
        "rates",
        "0.25",
        "2026",
    }
    assert ps.words("") == frozenset()


def test_texts() -> None:
    m = market(question="Who wins?", groupItemTitle="Alice")
    assert ps.pm_text(m) == "Who wins? Alice"
    assert ps.pm_text(market(question="Will Alice win?", groupItemTitle="Alice")) == (
        "Will Alice win?"
    )
    assert ps.kalshi_text(k("Title", "Sub")) == "Title Sub"


def test_suggest_ranks_by_similarity_and_date() -> None:
    pm = [
        market(
            question="Will Gavin Newsom win the 2028 Democratic nomination?",
            endDate=iso(NOW),
        ),
        market(question="Will it rain in Paris tomorrow?", endDate=iso(NOW)),
    ]
    kalshi = [
        k("Will Gavin Newsom be the Democratic nominee in 2028?", ticker="NEWSOM"),
        k(
            "Will Gavin Newsom be the 2028 Democratic nominee?",
            close=NOW + 2 * 86400,
            ticker="NEWSOM-LATE",
        ),
        k("Will Newsom win?", close=NOW + 30 * 86400, ticker="FAR"),
        k("Bitcoin above 100k?", ticker="BTC"),
    ]
    found = ps.suggest(pm, kalshi, min_similarity=0.3, per_market=2)
    assert [s.kalshi_ticker for s in found] == ["NEWSOM", "NEWSOM-LATE"]
    top = found[0]
    assert top.days_apart == 0.0 and top.score == top.similarity
    assert found[1].score < found[1].similarity
    row = top.to_dict()
    assert row["pm_token"] == pm[0].yes_token and row["kalshi_mid"] is not None
    assert len(ps.suggest(pm, kalshi, min_similarity=0.3)) == 1  # per_market=1
    assert ps.suggest(pm, kalshi, min_similarity=0.99) == []


def test_suggest_skips_non_binary_markets_and_tolerates_unknown_dates() -> None:
    multi = market(
        outcomes='["A", "B", "C"]',
        clobTokenIds='["1", "2", "3"]',
        outcomePrices='["0.3", "0.3", "0.4"]',
    )
    undated = market(question="Will Alice win the election?", endDate=None)
    kalshi = [k("Will Alice win the election?", close=None)]
    found = ps.suggest([multi, undated], kalshi)
    assert len(found) == 1 and found[0].days_apart is None


async def test_gather_reads_both_venues() -> None:
    transport = FakeTransport(
        {
            "/events/keyset": {
                "events": [
                    {
                        "id": "1",
                        "title": "E",
                        "markets": [gamma_market(), gamma_market(id="2", closed=True)],
                    }
                ]
            },
            "/events?": {
                "events": [{"event_ticker": "K", "markets": [kalshi_market()]}]
            },
        }
    )
    http = fake_http(transport, max_retries=0)
    pm, kalshi = await ps.gather(GammaClient(http), KalshiClient(http), pm_pages=1)
    assert len(pm) == 1 and len(kalshi) == 1
    assert "order=volume24hr" in transport.calls[0]
