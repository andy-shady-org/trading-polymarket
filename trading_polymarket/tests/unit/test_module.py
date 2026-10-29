from __future__ import annotations

from typing import Any

import pytest
from trading_core.module.base import (
    ExecutionRefused,
    MarketQuote,
    OrderRequest,
    Side,
)
from trading_core.positions import Position

from trading_polymarket.calibration import CalibrationTable, Observation
from trading_polymarket.clients.http import JsonHttp
from trading_polymarket.markets import Market
from trading_polymarket.module import EXIT_BID_TARGET, EXIT_CONVERGED, PolymarketModule
from trading_polymarket.pairs import Reference
from trading_polymarket.tests.support.factories import (
    CONDITION,
    NO,
    NOW,
    YES,
    book_payload,
    gamma_market,
    market,
    resolved,
)
from trading_polymarket.tests.support.fakes import (
    Clock,
    FakeTransport,
    RecordingHost,
    fake_http,
)

STATIONS = {"KDAL": {"lat": 32.8, "lon": -96.8}}


def build(transport: FakeTransport | None = None, **settings: Any) -> PolymarketModule:
    transport = transport or FakeTransport(
        {"/markets?": [gamma_market()], "/book": book_payload()}
    )
    return PolymarketModule(
        http=fake_http(transport, max_retries=0),
        clock=Clock(NOW),
        stations=STATIONS,
        **settings,
    )


def position(size: float = 10.0, token: str = YES, **kw: Any) -> Position:
    return Position(token, size=size, entry_price=0.5, cost_basis=size * 0.5, **kw)


def test_defaults_and_identity() -> None:
    module = PolymarketModule()
    assert module.name == "polymarket" and module.quote.symbol == "USDC"
    assert isinstance(module.http, JsonHttp)
    assert module.settings.enabled_lanes() == ["weather"]
    assert module.calibration.meta == {"identity": True}


async def test_quote_from_the_live_book_notifies_the_host() -> None:
    module = build()
    host = RecordingHost()
    module.bind(host)
    quote = await module.get_quote(YES)
    assert (quote.bid, quote.ask, quote.last) == (0.59, 0.61, 0.6)
    assert quote.timestamp == pytest.approx(NOW) and not quote.stale
    assert host.market_data == 1
    assert module.catalogue.cached(YES) is not None  # looked up on first quote
    await module.get_quote(YES)
    module2 = build()
    module2.catalogue.put([market()])
    assert (await module2.get_quote(YES)).bid == 0.59  # no host bound


async def test_quote_of_a_resolved_market_is_its_payout() -> None:
    module = build()
    module.catalogue.put([resolved(winner=1)])
    quote = await module.get_quote(NO)
    assert quote.bid == quote.ask == quote.last == 1.0
    assert (await module.get_quote(YES)).bid == 0.0


async def test_quote_when_the_book_is_gone() -> None:
    won = FakeTransport({"/markets?": [gamma_market(prices=["1", "0"], closed=True)]})
    assert (await build(won).get_quote(YES)).bid == 1.0
    pending = FakeTransport({"/markets?": [gamma_market(closed=True)]})
    quote = await build(pending).get_quote(YES)
    assert quote.stale and quote.last == 0.6 and quote.bid is None
    unknown = FakeTransport({"/markets?": []})
    with pytest.raises(Exception, match="no order book"):
        await build(unknown).get_quote(YES)


@pytest.mark.regression("TP-5")
async def test_quotes_and_values_use_each_tokens_own_price() -> None:
    # Gamma's lastTradePrice (0.6) is the Yes token's; the No token is 0.4.
    pending = FakeTransport({"/markets?": [gamma_market(closed=True)]})
    module = build(pending)
    quote = await module.get_quote(NO)
    assert quote.stale and quote.last == 0.4
    # Closed, awaiting resolution: valued at the token's final Gamma price.
    assert module.exit_value(position(10, token=NO)) == pytest.approx(4.0)
    # Open market whose book has no bids: nothing can be sold, worth 0 -
    # never a mark of ~1 from the ask side or another token's price.
    one_sided = FakeTransport(
        {
            "/markets?": [gamma_market()],
            "/book": book_payload(bids=[], asks=[(0.999, 10)]),
        }
    )
    module = build(one_sided)
    quote = await module.get_quote(YES)
    assert quote.bid is None and quote.mark == 0.6  # the token's own price
    assert module.exit_value(position(1000)) == 0.0


def test_complement_of_cached_binary_markets() -> None:
    module = build()
    assert module.complement_of(YES) is None
    module.catalogue.put([market()])
    assert module.complement_of(YES) == NO
    three = Market.from_gamma(
        gamma_market(
            clobTokenIds='["a","b","c"]',
            outcomes='["A","B","C"]',
            outcomePrices='["0.1","0.2","0.7"]',
        )
    )
    module.catalogue.put([three])
    assert module.complement_of("a") is None


async def test_balance_and_live_orders_are_refused() -> None:
    module = build()
    with pytest.raises(ExecutionRefused):
        await module.get_balance()
    order = OrderRequest(YES, Side.BUY, notional=10)
    with pytest.raises(ExecutionRefused, match="not implemented"):
        await module.execute(order, paper=False)


async def test_paper_execution() -> None:
    module = build()
    fill = await module.execute(OrderRequest(YES, Side.BUY, notional=10), paper=True)
    assert fill.simulated and fill.size > 0


def test_should_exit_on_resolution_and_bid_target() -> None:
    module = build(exit_at_bid=0.97)
    assert module.should_exit(position(), None, NOW) is None
    module.catalogue.put([market()])
    high = MarketQuote(YES, bid=0.98, ask=0.99)
    decision = module.should_exit(position(), high, NOW)
    assert decision is not None and decision.reason == EXIT_BID_TARGET
    assert module.should_exit(position(), MarketQuote(YES, bid=0.5), NOW) is None
    module.catalogue.put([resolved(winner=0)])
    decision = module.should_exit(position(), None, NOW)
    assert decision is not None and decision.reason == "resolved"
    assert "Yes paid 1" in decision.detail
    assert build().should_exit(position(), high, NOW) is None  # target off


async def test_exit_value_walks_the_bids_net_of_fee() -> None:
    module = build()
    assert module.exit_value(position(), MarketQuote(YES, bid=0.4)) == pytest.approx(4)
    await module.get_quote(YES)
    value = module.exit_value(position(60))
    gross = 0.59 * 50 + 0.58 * 10
    fee = round(50 * 0.05 * 0.59 * 0.41 + 10 * 0.05 * 0.58 * 0.42, 5)
    assert value == pytest.approx(gross - fee)
    module.catalogue._by_token.clear()
    assert module.exit_value(position(60)) == pytest.approx(gross)
    module.catalogue.put([resolved(winner=0)])
    assert module.exit_value(position(60)) == pytest.approx(60)
    assert module.exit_value(position(60, token=NO)) == 0.0


def test_formatting() -> None:
    module = build()
    assert module.format_price(0.615) == "61.5¢" and module.format_price(None) == "-"
    assert module.format_price(-1) == "-" and module.format_price(0) == "0.0¢"
    assert (
        module.format_size(1234.5) == "1,234.50" and module.format_size(None) == "0.00"
    )
    assert module.format_amount(12.5) == "$12.50"
    assert module.instrument_label(YES) == "111111…1111"
    assert module.instrument_label("short") == "short"
    assert module.instrument_label(YES, "Dallas 74-75°F") == "Dallas 74-75°F"
    assert module.instrument_label(YES, "x" * 40).endswith("…")


async def test_status_and_strategy_rows() -> None:
    module = build(
        FakeTransport({"/markets?": [gamma_market()]}),
        favourite={"enabled": True},
        momentum={"enabled": True},
    )
    assert (await module.get_quote(YES)).stale  # 404 book: counted as a failure
    rows = dict(module.status_rows())
    assert rows["api failures"] == "1" and "last api error" in rows
    strategy = dict(module.strategy_rows())
    assert strategy["lanes"] == "weather, favourite, momentum"
    assert "NO CALIBRATION" in strategy["favourite"]
    assert "research" in strategy["momentum"]
    table = CalibrationTable.build([Observation(0.9, 1, True)])
    calibrated = PolymarketModule(
        http=fake_http(), calibration=table, favourite={"enabled": True}
    )
    assert "calibrated" in dict(calibrated.strategy_rows())["favourite"]
    off = build(weather={"enabled": False})
    assert dict(off.strategy_rows()) == {"lanes": "none"}
    assert dict(build().status_rows()).keys() == {
        "api requests",
        "api failures",
        "markets cached",
    }


def test_public_identifiers_and_provenance() -> None:
    module = build()
    assert module.is_public_identifier(YES)
    assert module.is_public_identifier(CONDITION)
    assert not module.is_public_identifier("12345")
    assert not module.is_public_identifier("0x" + "z" * 10)
    prov = module.provenance()
    assert prov["calibration_identity"] is True
    assert prov["settings"]["weather"]["enabled"] is True
    assert len(prov["calibration_sha256"]) == 64


def test_pipeline_is_built_once_from_the_enabled_lanes() -> None:
    module = build(
        favourite={"enabled": True}, momentum={"enabled": True, "news": True}
    )
    pipeline = module.pipeline()
    assert pipeline is not None and module.pipeline() is pipeline
    assert [s.name for s in pipeline.scouts] == [
        "weather-events",
        "closing-favourites",
        "sharp-moves",
    ]
    assert module.weather_model is not None
    assert build(weather={"enabled": False}).pipeline() is None


def test_calibration_file_is_loaded(tmp_path) -> None:  # noqa: ANN001
    path = CalibrationTable.build([Observation(0.9, 1, True)]).save(tmp_path / "c.json")
    module = PolymarketModule(http=fake_http(), favourite={"calibration_path": path})
    assert module.calibration.samples(0.9, 1) == 1


def test_reference_lanes_join_the_pipeline_and_rows() -> None:
    module = build(
        weather={"enabled": False},
        fed={"enabled": True},
        crossvenue={"enabled": True, "reference": "bid"},
    )
    pipeline = module.pipeline()
    assert pipeline is not None
    assert [s.name for s in pipeline.scouts] == [
        "fed-vs-kalshi",
        "crossvenue-vs-kalshi",
    ]
    rows = dict(module.strategy_rows())
    assert rows["lanes"] == "fed, crossvenue"
    assert rows["fed"].startswith("vs Kalshi mid") and "bid" in rows["crossvenue"]
    assert module.kalshi.base_url == module.settings.kalshi_url
    assert module.references.ttl == 60.0


def test_reference_positions_exit_on_convergence() -> None:
    module = build(fed={"enabled": True})
    held = position(strategy="fed")
    quote = MarketQuote(YES, bid=0.61, ask=0.62)
    assert module.should_exit(held, quote, NOW) is None  # no reference yet
    module.references.remember(YES, Reference(0.60, 0.62, 5000.0, NOW))
    decision = module.should_exit(held, quote, NOW)
    assert decision is not None and decision.reason == EXIT_CONVERGED
    assert "Kalshi 0.610" in decision.detail
    assert module.should_exit(held, MarketQuote(YES, bid=0.55), NOW) is None
    assert module.should_exit(held, None, NOW) is None
    assert module.should_exit(position(strategy="weather"), quote, NOW) is None
