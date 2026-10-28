"""The installed entry point makes ``"module": "polymarket"`` work in trading-core."""

from __future__ import annotations

import json
from pathlib import Path

from trading_core.cli.audit import build_parser, run_audit_cli
from trading_core.module.registry import available_modules, load_module

from trading_polymarket.module import PolymarketModule
from trading_polymarket.research.records import append_jsonl, round_trip
from trading_polymarket.tests.support.factories import NOW


def test_entry_point_builds_the_module() -> None:
    assert "polymarket" in available_modules()
    module = load_module("polymarket", bankroll=250, weather={"lead_days": 0})
    assert isinstance(module, PolymarketModule)
    assert module.settings.bankroll == 250


def test_configs_load_and_build(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3] / "configs"
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text())
        module = load_module(data["module"], **data.get("module_settings", {}))
        assert isinstance(module, PolymarketModule), path.name


def test_trading_core_audit_judges_backtest_records(tmp_path: Path) -> None:
    path = tmp_path / "backtest.jsonl"
    rows = []
    for day in range(6):
        rows += round_trip(
            instrument_id=f"t{day}",
            name="n",
            strategy="weather",
            reason="r",
            entry_time=NOW + day * 86400,
            entry_price=0.5,
            notional=10,
            entry_fee=0.0,
            exit_time=NOW + day * 86400 + 3600,
            exit_price=1.0,
        )
    append_jsonl(path, rows)
    parser = build_parser()
    args = parser.parse_args(
        [
            "verdict",
            "--path",
            str(path),
            "--min-positions",
            "5",
            "--json",
            "--strategy",
            "weather",
        ]
    )
    assert run_audit_cli(args) == 0
