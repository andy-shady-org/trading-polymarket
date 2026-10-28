from __future__ import annotations

from datetime import date

import pytest

from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.research.history import (
    HistoryRow,
    _windows,
    collect,
    load_rows,
    market_row,
    parse_day,
)
from trading_polymarket.research.records import append_jsonl
from trading_polymarket.tests.support.factories import (
    NOW,
    gamma_market,
    history_row,
    resolved,
)
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http


def test_row_parsing_and_price_lookup() -> None:
    row = HistoryRow.from_dict(history_row())
    assert row.winner == 0 and row.token_ids[0] == "11111111"
    assert row.price_at(NOW - 100 * 3600) is None
    assert row.price_at(NOW - 50 * 3600) == 0.85
    assert row.price_at(NOW, 1) == pytest.approx(0.1)


def test_market_row_and_loading(tmp_path) -> None:  # noqa: ANN001
    row = market_row(resolved(winner=1), [(1.0, 0.5)])
    assert row["winner"] == 1 and row["history"] == [[1, 0.5]]
    path = tmp_path / "h.jsonl"
    append_jsonl(path, [history_row(end_time=5), {"bad": 1}, history_row(end_time=2)])
    assert [r.end_time for r in load_rows(path)] == [2, 5]


def test_windows_and_day_parsing() -> None:
    assert _windows(date(2026, 1, 1), date(2026, 1, 8), 3) == [
        ("2026-01-01T00:00:00Z", "2026-01-04T00:00:00Z"),
        ("2026-01-04T00:00:00Z", "2026-01-07T00:00:00Z"),
        ("2026-01-07T00:00:00Z", "2026-01-08T00:00:00Z"),
    ]
    assert parse_day("2026-10-28") == date(2026, 10, 28)


async def test_collect_appends_new_resolved_markets_once(
    tmp_path,
) -> None:  # noqa: ANN001
    won = gamma_market(prices=["1", "0"], closed=True)
    markets = [
        won,
        gamma_market(id="2", yes="3" * 30, no="4" * 30),  # unresolved
        gamma_market(
            id="3",
            yes="5" * 30,
            no="6" * 30,
            prices=["0", "1"],
            closed=True,
            volumeNum=10,
        ),
        gamma_market(id="4", yes="7" * 30, no="8" * 30, prices=["0", "1"], closed=True),
        gamma_market(id="5", yes="9" * 30, no="0" * 30, prices=["0", "1"], closed=True),
    ]
    history = {"history": [{"t": NOW - 3600, "p": 0.9}]}

    def prices(url: str) -> object:
        if "9" * 30 in url:
            return OSError("x")
        if "7" * 30 in url:
            return {"history": []}
        return history

    transport = FakeTransport(
        {"/markets/keyset": {"markets": markets}, "/prices-history": prices}
    )
    http = fake_http(transport, max_retries=0)
    path = tmp_path / "h.jsonl"
    lines: list[str] = []
    written = await collect(
        GammaClient(http),
        ClobClient(http),
        start=date(2026, 10, 1),
        end=date(2026, 10, 3),
        path=path,
        min_volume=1000,
        max_markets=10,
        progress=lines.append,
    )
    assert written == 1 and [r.market_id for r in load_rows(path)] == ["100"]
    assert any(line.startswith("5:") for line in lines)  # the failed fetch
    assert any("startTs=" in url for url in transport.calls)
    again = await collect(
        GammaClient(http),
        ClobClient(http),
        start=date(2026, 10, 1),
        end=date(2026, 10, 2),
        path=path,
    )
    assert again == 0


async def test_collect_caps_markets_per_window(tmp_path) -> None:  # noqa: ANN001
    markets = [
        gamma_market(
            id=str(i), yes=f"{i}" * 30, no=f"9{i}" * 15, prices=["1", "0"], closed=True
        )
        for i in range(1, 5)
    ]
    transport = FakeTransport(
        {
            "/markets/keyset": {"markets": markets},
            "/prices-history": {"history": [{"t": NOW, "p": 0.5}]},
        }
    )
    http = fake_http(transport)
    written = await collect(
        GammaClient(http),
        ClobClient(http),
        start=date(2026, 10, 1),
        end=date(2026, 10, 7),
        path=tmp_path / "h.jsonl",
        max_markets=2,
        window_days=3,
    )
    assert written == 2
