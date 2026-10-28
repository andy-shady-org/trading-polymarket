"""trading-core's engine running the Polymarket module end to end (paper).

Cycle 1 prices the weather event, buys mispriced buckets by walking the book
and records the trades; the market then resolves and cycle 2 redeems every
position at 1 or 0. The audit trail must reproduce the engine's numbers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from trading_core.accounting.audit import load_audit_records
from trading_core.accounting.pnl import summarize_pnl, trade_payloads
from trading_core.config.settings import EngineSettings
from trading_core.engine.engine import TradingEngine

from trading_polymarket.module import PolymarketModule
from trading_polymarket.tests.support.factories import (
    NOW,
    book_payload,
    forecast_payload,
    metar_row,
    weather_event,
)
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http


class EngineClock:
    def __init__(self) -> None:
        self.now = NOW
        self.mono = 1000.0

    def __call__(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.now += seconds
        self.mono += seconds


def engine_for(
    tmp_path: Path, transport: FakeTransport, clock: EngineClock
) -> TradingEngine:
    settings = EngineSettings.from_mapping(
        {
            "module": "polymarket",
            "mode": "paper",
            "order_size": 10,
            "paper_starting_balance": 1000,
            "max_signals_per_cycle": 5,
            "risk": {
                "max_total_exposure": 200,
                "max_position_size": 50,
                "max_active_positions": 10,
                "max_concentration_pct": 1.0,
            },
            "breaker": {
                "max_daily_drawdown_pct": 0.9,
                "profit_drawdown_tolerance_pct": 0.9,
            },
            "module_settings": {
                "weather": {"models": ["ecmwf_ifs025", "gfs_seamless"]}
            },
            "daily_summary_hour_utc": None,
            "event_log_path": None,
            "log_file": None,
            "status_path": str(tmp_path / "status.json"),
            "audit_log_path": str(tmp_path / "audit.jsonl"),
        }
    )
    module = PolymarketModule(
        http=fake_http(transport, max_retries=0),
        clock=clock,
        stations={"KDAL": {"lat": 32.8, "lon": -96.8}},
        **settings.module_settings,
    )
    return TradingEngine(module, settings, clock=clock, monotonic=clock.monotonic)


def resolved_markets(event: dict[str, Any], winner: int) -> list[dict[str, Any]]:
    out = []
    for index, raw in enumerate(event["markets"]):
        out.append(
            {
                **raw,
                "closed": True,
                "acceptingOrders": False,
                "outcomePrices": json.dumps(
                    ["1", "0"] if index == winner else ["0", "1"]
                ),
            }
        )
    return out


async def test_buy_then_redeem_at_resolution(tmp_path: Path) -> None:
    event = weather_event()
    transport = FakeTransport(
        {
            "/events/keyset": {"events": [event]},
            "/markets?": event["markets"],
            "/v1/forecast": forecast_payload(),
            "/api/data/metar": [metar_row(NOW - 3600)],
            "/book": book_payload(bids=[(0.08, 500)], asks=[(0.10, 500)]),
        }
    )
    clock = EngineClock()
    engine = engine_for(tmp_path, transport, clock)
    await engine.start()
    await engine.run_cycle()
    bought = len(engine.book)
    assert bought >= 1 and engine.totals.buys == bought
    strategies = {p.strategy for p in engine.book}
    assert strategies == {"weather"}

    # The day ends; 76-77°F wins. Books disappear, Gamma shows the result.
    transport.routes["/events/keyset"] = {"events": []}
    transport.routes["/markets?"] = resolved_markets(event, winner=2)
    transport.routes.pop("/book")
    clock.advance(36 * 3600)
    await engine.run_cycle()
    assert len(engine.book) == 0
    await engine.shutdown()

    trades = trade_payloads(load_audit_records(tmp_path / "audit.jsonl"))
    sells = [t for t in trades if t["action"] == "sell"]
    assert len(sells) == bought and {t["reason"] for t in sells} == {"resolved"}
    assert {t["price"] for t in sells} <= {0.0, 1.0}
    summary = summarize_pnl(trades)["totals"]
    assert summary["net_pnl"] == pytest.approx(engine.totals.net_pnl)
    assert engine.balance == pytest.approx(1000 + sum(t["cash_flow"] for t in trades))
    assert all(t["mode"] == "paper" and t["module"] == "polymarket" for t in trades)
