"""Unit tests for ``clients/spot.py``: one-second spot closes (FEAT-146)."""

from __future__ import annotations

from typing import Any

from trading_polymarket.clients.spot import SpotClient, parse_klines
from trading_polymarket.tests.support.fakes import FakeTransport, Sequenced, fake_http


def candle(t: float, close: float) -> list[Any]:
    return [int(t * 1000), "1", "2", "0.5", str(close), "9"]


def test_candles_are_parsed_and_malformed_ones_skipped() -> None:
    payload = [candle(10, 100.5), "x", [1, 2], [None, 1, 1, 1, "y"]]
    assert parse_klines(payload) == [(10.0, 100.5)]
    assert parse_klines({"code": 0}) == []


async def test_pages_run_from_the_last_candle_to_the_end() -> None:
    transport = FakeTransport(
        {
            "/api/v3/klines": Sequenced(
                [candle(100, 1.0), candle(101, 2.0)],
                [candle(101, 2.0), candle(103, 3.0), candle(110, 9.0)],
            )
        }
    )
    spot = SpotClient(fake_http(transport), base_url="https://s.test")
    found = await spot.seconds("BTCUSDT", start=100, end=105)
    # The repeated candle is not counted twice; one past the end is dropped.
    assert found == [(100.0, 1.0), (101.0, 2.0), (103.0, 3.0)]
    assert (
        "startTime=100000" in transport.calls[0]
        and "endTime=104999" in transport.calls[0]
    )
    assert "startTime=102000" in transport.calls[1]
    assert (
        "interval=1s" in transport.calls[0] and "symbol=BTCUSDT" in transport.calls[0]
    )


async def test_an_empty_answer_ends_the_read() -> None:
    transport = FakeTransport({"/api/v3/klines": []})
    spot = SpotClient(fake_http(transport))
    assert await spot.seconds("BTCUSDT", start=0, end=5000) == []
    assert len(transport.calls) == 1


async def test_the_read_ends_at_the_end() -> None:
    transport = FakeTransport({"/api/v3/klines": [candle(100, 1.0), candle(101, 2.0)]})
    spot = SpotClient(fake_http(transport))
    assert len(await spot.seconds("BTCUSDT", start=100, end=102)) == 2
    assert len(transport.calls) == 1
