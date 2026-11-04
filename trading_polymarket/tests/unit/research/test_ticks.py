"""Unit tests for ``research/ticks.py``: the book and spot recorder (FEAT-147)."""

from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.http import Response
from trading_polymarket.research import ticks
from trading_polymarket.research.ticks import (
    Book,
    BookStream,
    SpotStream,
    TickWriter,
    WindowMarket,
    day_of,
    parse_window_market,
    probe_loop,
    probe_once,
    record,
    window_markets,
    window_start,
)
from trading_polymarket.tests.support.fakes import Clock, FakeTransport, fake_http

START = 1793793900  # a 5-minute window start (2026-11-04 10:45 UTC)
UP, DOWN = "111", "222"


def raw_market(start: int = START, **extra: Any) -> dict[str, Any]:
    return {
        "slug": f"btc-updown-5m-{start}",
        "conditionId": f"0xc{start}",
        "outcomes": '["Up", "Down"]',
        "clobTokenIds": json.dumps([UP if start == START else "333", DOWN]),
        **extra,
    }


class FakeWs:
    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.closed = False

    async def send_json(self, message: Any) -> None:
        self.sent.append(message)

    async def send_str(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True


def read_rows(path: Path) -> list[Any]:
    opener: Any = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def market() -> WindowMarket:
    return WindowMarket("s", START, START + 300, "0xc", {UP: f"{START}:0"})


def book_stream(tmp_path: Path, clock: Clock, **options: Any) -> BookStream:
    async def resolve(start: int) -> list[WindowMarket]:
        assert start == START
        return [
            WindowMarket(
                "btc-updown-5m-x",
                START,
                START + 300,
                "0xc",
                {UP: f"{START}:0", DOWN: f"{START}:1"},
            )
        ]

    return BookStream(
        TickWriter(tmp_path),
        resolve,
        300,
        clock=clock,
        log=lambda _: None,
        stop=asyncio.Event(),
        **options,
    )


def test_the_writer_keeps_one_file_a_name_and_day(tmp_path: Path) -> None:
    writer = TickWriter(tmp_path)
    day1, day2 = START * 1000, (START + 86400) * 1000
    writer.write("spot", [day1, 1], rx=day1)
    writer.write("spot", [day1, 2], rx=day1)
    writer.write("probes", [day1, 3], rx=day1)
    writer.flush()
    writer.write("spot", [day2, 4], rx=day2)
    writer.close()
    first = tmp_path / day_of(day1)
    assert read_rows(first / "spot.jsonl.gz") == [[day1, 1], [day1, 2]]
    assert read_rows(first / "probes.jsonl") == [[day1, 3]]
    assert read_rows(tmp_path / day_of(day2) / "spot.jsonl.gz") == [[day2, 4]]
    assert writer.counts == {"spot": 3, "probes": 1}


def test_a_book_keeps_its_top() -> None:
    book = Book()
    assert book.top() == (None, None, None, None)
    book.reset(
        [{"price": "0.4", "size": "10"}, {"price": "x"}, {"price": "0.3", "size": "0"}],
        "not a list",
    )
    assert book.top() == (0.4, 10.0, None, None)
    book.set("SELL", 0.6, 5)
    book.set("SELL", 0.55, 2)
    book.set("BUY", 0.4, 0)
    assert book.top() == (None, None, 0.55, 2.0)


def test_markets_are_parsed_from_gamma() -> None:
    parsed = parse_window_market(raw_market(), 300)
    assert parsed == WindowMarket(
        f"btc-updown-5m-{START}",
        START,
        START + 300,
        f"0xc{START}",
        {UP: f"{START}:0", DOWN: f"{START}:1"},
    )
    assert parsed is not None and parsed.to_dict(7)["rx"] == 7
    assert parse_window_market(raw_market(slug="btc-updown-5m-x"), 300) is None
    assert parse_window_market(raw_market(slug=""), 300) is None
    assert parse_window_market(raw_market(outcomes='["Yes", "No"]'), 300) is None
    assert parse_window_market(raw_market(clobTokenIds="not json"), 300) is None
    assert parse_window_market(raw_market(clobTokenIds='{"a": 1}'), 300) is None
    listed = raw_market(outcomes=["Up", "Down"], clobTokenIds=[UP, DOWN])
    assert parse_window_market(listed, 300) is not None
    assert window_start(START + 299.9, 300) == START


async def test_the_window_and_the_next_are_looked_up() -> None:
    transport = FakeTransport(
        {"/markets?": [raw_market(START + 300), raw_market(slug="odd"), raw_market()]}
    )
    gamma = GammaClient(fake_http(transport), base_url="https://g.test")
    found = await window_markets(gamma, "btc", "5m", START)
    assert [m.start for m in found] == [START, START + 300]
    url = transport.calls[0]
    assert f"slug=btc-updown-5m-{START}" in url and "closed" not in url


async def test_the_book_stream_records_tops_and_trades(tmp_path: Path) -> None:
    clock = Clock(START + 10)
    stream = book_stream(tmp_path, clock, ping_seconds=0.001)
    ws = FakeWs()
    await stream.on_stream_connected(ws)
    assert ws.sent[0] == {"assets_ids": [UP, DOWN], "type": "market"}
    await asyncio.sleep(0.01)
    assert "PING" in ws.sent
    snapshot = {
        "event_type": "book",
        "asset_id": UP,
        "timestamp": "1",
        "bids": [{"price": "0.02", "size": "100"}],
        "asks": [{"price": "0.03", "size": "50"}],
    }
    await stream.on_stream_message(
        [
            snapshot,
            "not a mapping",
            {"asset_id": DOWN, "bids": [], "asks": [{"price": "0.98", "size": "5"}]},
            {"event_type": "book", "asset_id": "999", "bids": [], "asks": []},
        ],
        ws,
    )
    await stream.on_stream_message(snapshot, ws)  # the same top: no new row
    changes = {
        "event_type": "price_change",
        "timestamp": "x",
        "price_changes": [
            {"asset_id": UP, "price": "0.03", "size": "0", "side": "SELL"},
            {"asset_id": UP, "price": "0.04", "size": "20", "side": "SELL"},
            {"asset_id": UP, "price": "bad", "size": "1", "side": "SELL"},
            {"asset_id": "999", "price": "0.5", "size": "1", "side": "BUY"},
            "not a mapping",
        ],
    }
    legacy = {
        "event_type": "price_change",
        "asset_id": DOWN,
        "changes": [{"price": "0.97", "size": "3", "side": "BUY"}],
    }
    trades = [
        {
            "event_type": "last_trade_price",
            "asset_id": UP,
            "price": "0.04",
            "size": "20",
            "side": "BUY",
            "timestamp": "5",
            "transaction_hash": "0xABC",
        },
        {
            "event_type": "last_trade_price",
            "asset_id": "999",
            "price": "1",
            "size": "1",
        },
        {"event_type": "last_trade_price", "asset_id": UP, "price": "x", "size": "1"},
        {"event_type": "price_change", "changes": "not a list"},
        {"event_type": "tick_size_change", "asset_id": UP},
    ]
    await stream.on_stream_message([changes, legacy, *trades], ws)
    assert not ws.closed
    clock.advance(300)  # two seconds into the next window: roll
    await stream.on_stream_message([], ws)
    assert ws.closed and stream.rolling
    stream.on_stream_ended()  # a planned roll: nothing logged
    assert not stream.rolling
    stream.on_stream_closed()
    stream.on_stream_closed()
    stream.writer.close()
    day = tmp_path / day_of(round(clock.now * 1000))
    quotes = read_rows(day / "quotes.jsonl.gz")
    assert [q[1:] for q in quotes] == [
        [1, f"{START}:0", 0.02, 100.0, 0.03, 50.0],
        [None, f"{START}:1", None, None, 0.98, 5.0],
        [None, f"{START}:0", 0.02, 100.0, 0.04, 20.0],
        [None, f"{START}:1", 0.97, 3.0, 0.98, 5.0],
    ]
    assert [t[1:] for t in read_rows(day / "trades.jsonl.gz")] == [
        [5, f"{START}:0", "BUY", 0.04, 20.0, "0xabc"]
    ]
    assert read_rows(day / "markets.jsonl")[0]["tokens"] == {
        UP: f"{START}:0",
        DOWN: f"{START}:1",
    }
    assert stream.messages == 11


async def test_a_connection_early_in_a_window_takes_the_last_one(
    tmp_path: Path,
) -> None:
    clock = Clock(START + 300 + 1)  # one second into the next window
    stream = book_stream(tmp_path, clock)
    ws = FakeWs()
    await stream.on_stream_connected(ws)
    assert stream.window == START
    await stream.on_stream_message([], ws)
    assert not ws.closed
    stream.on_stream_closed()
    stream.writer.close()


async def test_the_spot_stream_writes_price_changes(tmp_path: Path) -> None:
    logged: list[str] = []
    clock = Clock(START)
    stream = SpotStream(
        TickWriter(tmp_path),
        "wss://s.test",
        clock=clock,
        log=logged.append,
        stop=asyncio.Event(),
    )
    ws = FakeWs()
    await stream.on_stream_connected(ws)
    for message in (
        {"p": "100.5", "E": 1, "T": 2},
        {"p": "100.5", "E": 3, "T": 4},
        {"p": "100.6", "E": 5, "T": 6},
        {"p": "x"},
        "not a mapping",
    ):
        await stream.on_stream_message(message, ws)
    stream.writer.close()
    rows = read_rows(tmp_path / day_of(START * 1000) / "spot.jsonl.gz")
    assert [r[1:] for r in rows] == [[1, 2, 100.5], [5, 6, 100.6]]
    assert stream.messages == 3 and logged == ["spot: connected to wss://s.test"]
    # The callbacks the stream loop calls on the way.
    assert not stream.stream_stop_requested()
    assert stream.stream_connect_url() == "wss://s.test"
    stream.stream_log("a")
    stream.on_stream_error("b")
    stream.on_stream_exception(OSError("c"), 2.0)
    stream.on_stream_ended()
    stream.on_stream_closed()
    assert logged[1:3] == ["a", "b"] and "reconnecting in 2s" in logged[3]
    assert logged[4] == "SpotStream: the stream ended; reconnecting"


async def test_a_probe_times_a_round_trip_or_records_a_failure(tmp_path: Path) -> None:
    writer = TickWriter(tmp_path)
    clock = Clock(START)
    good = fake_http(FakeTransport({"/time": 1793793900}), max_retries=0)
    timed = await probe_once(good, writer, clock=clock, url="https://c.test/time")
    assert timed is not None and timed >= 0
    bad = fake_http(FakeTransport({"/time": Response(500, b"{}")}), max_retries=0)
    assert await probe_once(bad, writer, clock=clock, url="https://c.test/time") is None
    stop = asyncio.Event()
    stop.set()
    await probe_loop(good, writer, clock=clock, stop=stop)  # stopped: no probe
    writer.close()
    rows = read_rows(tmp_path / day_of(START * 1000) / "probes.jsonl")
    assert [r[2] for r in rows] == [1793793900, None] and rows[1][1] is None


async def test_record_runs_every_loop_until_the_deadline(tmp_path: Path) -> None:
    transport = FakeTransport({"/markets?": [raw_market()], "/time": 1})
    gamma = GammaClient(fake_http(transport), base_url="https://g.test")
    logged: list[str] = []

    async def runner(host: Any) -> None:
        ws = FakeWs()
        await host.on_stream_connected(ws)
        message = (
            {"p": "100", "E": 1, "T": 1}
            if isinstance(host, SpotStream)
            else {"event_type": "book", "asset_id": UP, "bids": [], "asks": []}
        )
        await host.on_stream_message(message, ws)

    counts = await record(
        gamma,
        fake_http(transport, max_retries=0),
        directory=tmp_path,
        hours=1e-6,
        runner=runner,
        clock=Clock(START + 10),
        log=logged.append,
    )
    assert counts["spot"] == 1 and counts["markets"] == 1 and counts["probes"] >= 1
    assert counts["quotes"] == 1
    assert logged[-1].startswith("recorded: markets 1, probes")
    assert "spot: connected" in " ".join(logged)


async def test_record_refuses_an_unknown_asset(tmp_path: Path) -> None:
    gamma = GammaClient(fake_http(), base_url="https://g.test")
    with pytest.raises(ValueError, match="unknown asset"):
        await record(gamma, fake_http(), asset="ada", directory=tmp_path)


async def test_no_deadline_returns_at_once() -> None:
    await ticks.deadline(asyncio.Event(), None)


def test_only_price_moves_and_cheap_ask_sizes_are_written() -> None:
    worth = ticks._worth_writing
    assert worth((0.02, 1.0, 0.03, 5.0), None)
    assert worth((0.02, 1.0, 0.04, 5.0), (0.02, 1.0, 0.03, 5.0))  # the ask moved
    assert worth((0.01, 1.0, 0.03, 5.0), (0.02, 1.0, 0.03, 5.0))  # the bid moved
    assert worth((0.02, 1.0, 0.03, 4.0), (0.02, 1.0, 0.03, 5.0))  # cheap ask size
    assert not worth((0.02, 9.0, 0.03, 5.0), (0.02, 1.0, 0.03, 5.0))  # bid size
    assert not worth((0.96, 1.0, 0.97, 4.0), (0.96, 1.0, 0.97, 5.0))  # dear ask size
    assert not worth((0.5, 1.0, None, None), (0.5, 2.0, None, None))  # no ask
