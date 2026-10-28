from __future__ import annotations

import pytest
from trading_core.accounting.verdict import VerdictRules, evaluate_verdict

from trading_polymarket.research.records import (
    MODE_BACKTEST,
    append_jsonl,
    envelope,
    read_jsonl,
    round_trip,
)
from trading_polymarket.tests.support.factories import NOW


def test_jsonl_round_trip_skips_bad_lines(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "a" / "x.jsonl"
    assert list(read_jsonl(path)) == []
    assert append_jsonl(path, [{"a": 1}, {"b": 2}]) == 2
    with path.open("a") as handle:
        handle.write("\nnot json\n[1]\n")
    assert list(read_jsonl(path)) == [{"a": 1}, {"b": 2}]


def test_envelope() -> None:
    assert envelope({"x": 1}, 5) == {
        "timestamp": 5.0,
        "type": "trade",
        "state": MODE_BACKTEST,
        "payload": {"x": 1},
    }


def trip(exit_price: float, opened: float = NOW) -> list[dict]:
    return round_trip(
        instrument_id="tok",
        name="n",
        strategy="favourite",
        reason="r",
        entry_time=opened,
        entry_price=0.8,
        notional=8.0,
        entry_fee=0.1,
        exit_time=opened + 3600,
        exit_price=exit_price,
        metrics={"fair": 0.9},
    )


def test_round_trip_books_a_buy_and_its_sell() -> None:
    buy, sell = (r["payload"] for r in trip(1.0))
    assert buy["action"] == "buy" and buy["entry_metrics"] == {"fair": 0.9}
    assert buy["size"] == pytest.approx(10) and buy["mode"] == MODE_BACKTEST
    assert sell["action"] == "sell" and sell["proceeds"] == pytest.approx(10)
    assert sell["net_pnl"] == pytest.approx(2.0)
    assert buy["net_pnl"] == pytest.approx(-0.1)
    assert buy["position_id"] == sell["position_id"]


def test_trading_core_verdict_reads_backtest_records() -> None:
    records = [
        r for i in range(4) for r in trip(1.0 if i % 2 else 0.0, NOW + i * 86400)
    ]
    payloads = [r["payload"] | {"timestamp": r["timestamp"]} for r in records]
    verdict = evaluate_verdict(payloads, VerdictRules(min_positions=4))
    assert verdict["positions"] == 4
    assert verdict["net"] == pytest.approx(2 * 2.0 - 2 * 8.0 - 4 * 0.1)
