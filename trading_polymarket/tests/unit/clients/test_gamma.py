from __future__ import annotations

import pytest

from trading_polymarket.clients.gamma import GammaClient, _items, resolved_only
from trading_polymarket.tests.support.factories import (
    NO,
    YES,
    gamma_market,
    market,
    resolved,
)
from trading_polymarket.tests.support.fakes import FakeTransport, Sequenced, fake_http


def client(transport: FakeTransport) -> GammaClient:
    return GammaClient(fake_http(transport), base_url="https://g.test")


def test_items_shapes() -> None:
    assert _items([1], "markets") == ([1], None)
    assert _items({"markets": [1], "next_cursor": "c"}, "markets") == ([1], "c")
    assert _items({"markets": "x"}, "markets") == ([], None)
    assert _items(None, "markets") == ([], None)


async def test_markets_pages_with_the_cursor_and_skips_malformed() -> None:
    transport = FakeTransport(
        {
            "/markets/keyset": Sequenced(
                {
                    "markets": [gamma_market(), {"id": "bad"}, "junk"],
                    "next_cursor": "c1",
                },
                {"markets": [gamma_market(id="101", yes="7" * 30, no="8" * 30)]},
            )
        }
    )
    found = await client(transport).markets(max_pages=5, closed=False)
    assert [m.market_id for m in found] == ["100", "101"]
    assert "after_cursor=c1" in transport.calls[1]
    assert "closed=false" in transport.calls[0] and "limit=100" in transport.calls[0]


async def test_paging_stops_on_empty_page_and_page_limit() -> None:
    transport = FakeTransport({"/markets/keyset": {"markets": [], "next_cursor": "c"}})
    assert await client(transport).raw_markets(max_pages=3) == []
    assert transport.count("/markets/keyset") == 1
    transport = FakeTransport(
        {"/markets/keyset": {"markets": [gamma_market()], "next_cursor": "c"}}
    )
    assert len(await client(transport).raw_markets(max_pages=2)) == 2


async def test_events_return_markets_with_event_context() -> None:
    event = {"id": "e1", "title": "T", "markets": [gamma_market()]}
    transport = FakeTransport({"/events/keyset": {"events": [event, "junk"]}})
    pairs = await client(transport).events(tag_slug="weather")
    assert len(pairs) == 1
    raw, markets = pairs[0]
    assert raw["id"] == "e1" and markets[0].event_title == "T"


async def test_markets_by_tokens_batches_and_dedupes() -> None:
    transport = FakeTransport({"/markets?": [gamma_market(), gamma_market(), "junk"]})
    g = client(transport)
    found = await g.markets_by_tokens([YES, NO, ""] + [str(i) for i in range(25)])
    assert len(found) == 1
    # 27 tokens -> batches of 20; the 25 not found are asked again as closed.
    assert transport.count("/markets?") == 4
    assert transport.count("closed=true") == 2
    assert "clob_token_ids=" in transport.calls[0]
    assert (await g.market_by_token(YES)).market_id == "100"  # type: ignore[union-attr]
    assert await g.market_by_token("unknown") is None


@pytest.mark.regression("TP-9")
async def test_tokens_of_closed_markets_are_found_by_a_second_pass() -> None:
    # Gamma's default /markets query returns open markets only: a held
    # token whose market has closed is found only with closed=true.
    transport = FakeTransport(
        {
            "closed=true": [gamma_market(closed=True, prices=["1", "0"])],
            "/markets?": [],
        }
    )
    found = await client(transport).markets_by_tokens([YES])
    assert [m.closed for m in found] == [True]
    assert transport.count("closed=true") == 1 and transport.count("/markets?") == 2
    # Every token found by the first pass: no second request.
    open_only = FakeTransport({"/markets?": [gamma_market()]})
    assert len(await client(open_only).markets_by_tokens([YES, NO])) == 1
    assert open_only.count("/markets?") == 1


async def test_bad_market_payload_shape() -> None:
    transport = FakeTransport({"/markets?": {"markets": [{"id": "x"}]}})
    assert await client(transport).markets_by_tokens([YES]) == []


async def test_search_and_closed_markets() -> None:
    transport = FakeTransport(
        {
            "/public-search": {"events": [{"id": "1"}, "x"]},
            "/markets/keyset": {"markets": [gamma_market()]},
        }
    )
    g = client(transport)
    assert await g.search_events("rain") == [{"id": "1"}]
    found = await g.closed_markets(end_date_min="a", end_date_max="b", tag_slug="t")
    assert len(found) == 1
    assert (
        "end_date_min=a" in transport.calls[-1] and "tag_slug=t" in transport.calls[-1]
    )
    transport = FakeTransport({"/public-search": ["not", "a", "mapping"]})
    assert await client(transport).search_events("x") == []


def test_resolved_only() -> None:
    assert resolved_only([market(), resolved()]) == [resolved()]
