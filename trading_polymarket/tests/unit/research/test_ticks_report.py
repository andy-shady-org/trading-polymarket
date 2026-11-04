"""Unit tests for ``research/ticks_report.py``: reading a ``ticks`` recording."""

from __future__ import annotations

import gzip
from datetime import date
from pathlib import Path
from typing import Any

from trading_polymarket.clients.data_api import DataApiClient, TradePrint
from trading_polymarket.research.ticks import TickWriter, day_of
from trading_polymarket.research.ticks_report import (
    Quotes,
    Recording,
    Signal,
    decision,
    fetch_offsets,
    load_recording,
    match_offsets,
    median,
    nearest_round_trip,
    quantiles,
    receive_delays,
    round_trips,
    signals,
)
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http

W = 1793793900  # a window start, 2026-11-04 10:45 UTC
W2 = W + 300  # its ask is never taken (censored)
W0 = W - 600  # before the first spot price: no start price
W3 = W + 600  # no quotes recorded


def ms(seconds: float) -> int:
    return int(seconds * 1000)


def write_recording(directory: Path) -> None:
    writer = TickWriter(directory)
    at = ms(W)

    def spot(t: float, price: float) -> None:
        writer.write("spot", [ms(t) + 80, ms(t), ms(t), price], rx=at)

    def quote(rx: float, key: str, ask: float | None) -> None:
        writer.write("quotes", [ms(rx), ms(rx), key, None, None, ask, 10.0], rx=at)

    spot(W - 0.5, 100_000.0)  # the start price of W
    spot(W + 245, 99_900.0)  # Up -10 bp: too far; Down's ask is too dear
    spot(W + 250, 99_990.0)  # Up -1 bp: the signal
    spot(W + 260, 99_995.0)  # Up already signalled
    spot(W2 + 250, 100_000.0)
    spot(W3 + 250, 100_000.0)
    quote(W + 200, f"{W}:0", 0.03)
    quote(W + 200, f"{W}:1", 0.97)
    quote(W + 251, f"{W}:0", 0.05)  # repriced: the ask lived 1,000 ms
    quote(W2 + 200, f"{W2}:0", 0.04)
    quote(W2 + 200, f"{W2}:1", 0.97)
    quote(W2 + 300.005, f"{W2}:0", 0.50)  # after the window: censored
    writer.write("probes", [ms(W), 300.0, W], rx=at)
    writer.write("probes", [ms(W) + 1, None, None], rx=at)
    writer.write("trades", [at, ms(W + 1), f"{W}:0", "BUY", 0.03, 10.0, "0xaa"], rx=at)
    writer.write("trades", [at, ms(W + 2), f"{W}:0", "BUY", 0.03, 10.0, "0xaa"], rx=at)
    for start in (W0, W, W2, W3):
        writer.write(
            "markets",
            {
                "rx": at,
                "start": start,
                "end": start + 300,
                "condition_id": f"0x{start}",
            },
            rx=at,
        )
    writer.close()


def test_a_recording_is_read_in_time_order(tmp_path: Path) -> None:
    write_recording(tmp_path)
    folder = tmp_path / day_of(ms(W))
    with (folder / "spot.jsonl.gz").open("ab") as handle:
        handle.write(gzip.compress(b"not json\n")[:-8])  # a file still being written
    (tmp_path / "notes").mkdir()
    (tmp_path / "2026-11-03").mkdir()
    (tmp_path / "README").write_text("x")
    recording = load_recording(tmp_path, start=date(2026, 11, 4))
    assert recording.days == [day_of(ms(W))]
    assert len(recording.spot) == 6 and recording.spot[0][2] == 100_000.0
    assert receive_delays(recording) == [80.0] * 6
    assert round_trips(recording) == [300.0]
    assert sorted(recording.markets) == [W0, W, W2, W3]
    assert load_recording(tmp_path, end=date(2026, 11, 4)).days == ["2026-11-03"]
    assert load_recording(tmp_path / "missing").days == []


def test_a_broken_file_is_read_as_far_as_it_goes(tmp_path: Path) -> None:
    folder = tmp_path / "2026-11-04"
    folder.mkdir()
    (folder / "spot.jsonl.gz").write_bytes(b"not gzip at all")
    assert load_recording(tmp_path).spot == []


def test_signals_measure_the_stale_ask_against_our_delay(tmp_path: Path) -> None:
    write_recording(tmp_path)
    found = signals(load_recording(tmp_path))
    assert found == [
        Signal(W, 0, ms(W + 250), ms(W + 250) + 80, 0.03, 1000, False, 380.0),
        Signal(W2, 0, ms(W2 + 250), ms(W2 + 250) + 80, 0.04, 50_000, True, 380.0),
    ]
    assert all(s.takeable for s in found)
    assert not Signal(W, 0, 0, 0, 0.03, 100, False, 380.0).takeable
    assert not Signal(W, 0, 0, 0, 0.03, 100, False, None).takeable


def test_quotes_and_round_trips_by_time() -> None:
    quotes = Quotes([10, 20, 30], [0.03, 0.03, None])
    assert quotes.at(5) == (-1, None) and quotes.at(25) == (1, 0.03)
    assert quotes.gone(0, 0.03, 100) == 30  # the ask went
    assert quotes.gone(0, 0.03, 25) is None  # the window ended first
    assert Quotes([10, 20], [0.03, 0.03]).gone(0, 0.03, 100) is None  # never went
    recording = Recording(probes=[(100, None), (200, 50.0), (400, 70.0)])
    assert nearest_round_trip(recording, 260) == 50.0
    assert nearest_round_trip(recording, 390) == 70.0
    assert nearest_round_trip(recording, 999) == 70.0
    assert nearest_round_trip(Recording(probes=[(1, None)]), 5) is None


def test_the_decision() -> None:
    good = Signal(W, 0, 0, 0, 0.03, 1000, False, 300.0)
    bad = Signal(W, 0, 0, 0, 0.03, 100, False, 300.0)
    assert decision(2, [good]) == "not enough days (2 of 3)"
    assert decision(3, []) == "no signals"
    assert decision(3, [good, bad]) == "takeable"
    assert decision(3, [good, bad, bad]) == "not takeable"


def test_quantiles_and_median() -> None:
    assert quantiles([]) is None and median([]) is None
    assert quantiles([3.0, 1.0, 2.0]) == {"n": 3, "p10": 1.0, "p50": 2.0, "p90": 3.0}
    assert median([1.0, 2.0, 4.0]) == 2.0


def test_offsets_match_by_transaction(tmp_path: Path) -> None:
    trades: list[list[Any]] = [
        [0, 1000, "k", "BUY", 0.1, 1.0, "0xaa"],
        [0, 900, "k", "BUY", 0.1, 1.0, "0xaa"],
        [0, None, "k", "BUY", 0.1, 1.0, "0xbb"],
        [0, 5000, "k", "BUY", 0.1, 1.0, ""],
    ]
    prints = [
        TradePrint(3.0, 0, "BUY", 0.1, 1.0, "", "0xaa"),
        TradePrint(9.0, 0, "BUY", 0.1, 1.0, "", "0xcc"),
    ]
    assert match_offsets(trades, prints) == [3.0 - 0.9]


async def test_offsets_are_fetched_for_markets_already_over(tmp_path: Path) -> None:
    write_recording(tmp_path)
    recording = load_recording(tmp_path)
    recording.trades.append([0, 1, "999:0", "BUY", 0.1, 1.0, "0xzz"])  # not listed
    rows = [
        {
            "timestamp": W + 3,
            "outcome_index": 0,
            "side": "BUY",
            "price": 0.03,
            "size": 10,
            "transaction_hash": "0xAA",
        }
    ]
    transport = FakeTransport({"/v2/trades": {"data": rows, "pagination": {}}})
    data = DataApiClient(fake_http(transport), base_url="https://d.test")
    found = await fetch_offsets(recording, data, markets=5, now=W + 301)
    assert found == [2.0] and transport.count("/v2/trades") == 1
    assert await fetch_offsets(recording, data, markets=5, now=W) == []
