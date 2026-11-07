from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.http import HttpError
from trading_polymarket.research.arb import KIND_YES, SetQuote, event_sets
from trading_polymarket.research.arb_loop import (
    ArbRecorder,
    ArbWriter,
    Catalogue,
    Gap,
    Settings,
    day_of,
    read_catalogue,
    record,
)
from trading_polymarket.tests.support.factories import NOW, book_payload, gamma_market
from trading_polymarket.tests.support.fakes import Clock, FakeTransport, fake_http

FREE = {"feeSchedule": None, "feesEnabled": False}


def raw_leg(i: int, **extra: Any) -> dict[str, Any]:
    return gamma_market(
        id=str(i), yes=f"y{i}", no=f"n{i}", negRisk=True, **{**FREE, **extra}
    )


def event(event_id: str = "e1", legs: int = 2, **extra: Any) -> dict[str, Any]:
    return {
        "id": event_id,
        "slug": f"event-{event_id}",
        "title": f"Event {event_id}",
        "negRisk": True,
        "markets": [raw_leg(int(event_id[1:]) * 10 + i) for i in range(legs)],
        **extra,
    }


class Venue:
    """Gamma's events and a book per Yes token, changeable between ticks."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.asks: dict[str, list[tuple[float, float]]] = {}
        self.bids: dict[str, list[tuple[float, float]]] = {}
        self.missing: set[str] = set()
        self.transport = FakeTransport(
            {"/events/keyset": self._events, "/books": self._books}
        )
        http = fake_http(self.transport, max_retries=0)
        self.gamma = GammaClient(http)
        self.clob = ClobClient(http)

    def _events(self, url: str) -> dict[str, Any]:
        return {"events": self.events}

    def _books(self, url: str) -> list[dict[str, Any]]:
        tokens = set(self.asks) | set(self.bids)
        return [
            book_payload(t, bids=self.bids.get(t, []), asks=self.asks.get(t, []))
            for t in sorted(tokens - self.missing)
        ]

    def price(self, token: str, ask: float, size: float = 100, bid: float = 0.0):
        self.asks[token] = [(ask, size)]
        self.bids[token] = [(bid, size)] if bid else []


def recorder(venue: Venue, tmp_path: Path, clock: Clock, **settings: Any):
    return ArbRecorder(
        venue.gamma,
        venue.clob,
        ArbWriter(tmp_path),
        Settings(**settings),
        clock=clock,
    )


def rows(tmp_path: Path, name: str) -> list[dict[str, Any]]:
    path = tmp_path / day_of(NOW) / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def observations(tmp_path: Path) -> list[list[Any]]:
    path = tmp_path / day_of(NOW) / "observations.jsonl.gz"
    with gzip.open(path, "rt") as lines:
        return [json.loads(line) for line in lines]


def test_writer_appends_and_skips_empty(tmp_path: Path) -> None:
    writer = ArbWriter(tmp_path)
    writer.rows(NOW, "gaps", [])
    writer.observations(NOW, [])
    assert not (tmp_path / day_of(NOW)).exists()
    writer.rows(NOW, "gaps", [{"a": 1}])
    writer.observations(NOW, [[1, "k"]])
    assert rows(tmp_path, "gaps") == [{"a": 1}]
    assert observations(tmp_path) == [[1, "k"]]
    assert writer.counts == {"gaps": 1, "observations": 1}


def quote_of(max_profit: float, size: float = 10.0, best: float = 0.9) -> SetQuote:
    return SetQuote("e1:yes_set", best, size, max_profit, size, (None,) * 3, 5.0, True)


def test_gap_tracks_its_longest_run_at_the_qualifying_profit() -> None:
    spec = event_sets(event())[0]
    gap = Gap(spec, NOW, quote_of(6), qualify=5.0)
    for offset, profit in [(0, 6), (5, 7), (10, 4), (15, 6), (20, 6), (25, 6), (30, 6)]:
        gap.add(NOW + offset, quote_of(profit, size=offset + 1))
    row = gap.row(NOW + 35, "closed")
    assert row["run_seconds"] == 15 and row["run_reads"] == 4  # 15 s to 30 s
    assert row["reads"] == 7 and row["lifetime"] == 30
    assert row["peak_max_profit"] == 7 and row["peak_max_size"] == 31
    assert row["first_max_profit"] == 6 and row["peak_best_profit"] == 0.1
    assert not row["censored"] and row["reason"] == "closed"
    assert row["key"] == spec.key and row["qualify"] == 5.0
    assert gap.row(None, "stopped")["censored"]
    empty = Gap(spec, NOW, quote_of(1), qualify=5.0)
    empty.add(NOW, SetQuote("k", None, 0, 0, 0, (None,) * 3, 5, True))
    assert empty.row(NOW, "closed")["run_seconds"] == 0


def test_catalogue_counts_events_and_sets() -> None:
    found = Catalogue()
    found.add({"id": "plain", "negRisk": False}, 0.0)
    found.add(event("e1"), 0.0)
    found.add(event("e2", legs=1), 0.0)  # one outcome: no full set
    row = found.row(NOW, 3.0)
    assert row["events"] == 3 and row["neg_risk_events"] == 2
    assert row["sets"] == 2 and row["no_full_set"] == 1 and row["legs"] == 2
    assert row["augmented_sets"] == 0 and row["seconds"] == 3.0


async def test_read_catalogue_passes_over_every_page() -> None:
    venue = Venue([event("e1"), event("e2")])
    found = await read_catalogue(venue.gamma, max_pages=3)
    assert sorted(found.sets) == [
        "e1:no_set",
        "e1:yes_set",
        "e2:no_set",
        "e2:yes_set",
    ]


async def loaded(venue: Venue, tmp_path: Path, clock: Clock, **settings: Any):
    rec = recorder(venue, tmp_path, clock, **settings)
    await rec.catalogue_step(clock())
    assert rec.loading is not None
    await rec.loading
    await rec.catalogue_step(clock())
    return rec


async def test_a_gap_opens_on_a_sweep_is_rechecked_and_closes(tmp_path: Path) -> None:
    venue = Venue([event("e1")])
    clock = Clock(NOW)
    venue.price("y10", ask=0.40, bid=0.30)
    venue.price("y11", ask=0.50, bid=0.40)
    rec = await loaded(venue, tmp_path, clock)
    assert rows(tmp_path, "catalogue")[0]["sets"] == 2
    await rec.tick()  # the sweep: the Yes set costs 0.90 for 100 sets
    assert list(rec.gaps) == ["e1:yes_set"]
    assert rec.watched == {"e1:yes_set"}  # the No set costs 1.30: not watched
    sweep = rows(tmp_path, "sweeps")[0]
    assert sweep["sets"] == 2 and sweep["tokens"] == 2 and sweep["open"] == 1
    assert sweep["missing"] == 0 and sweep["watched"] == 1
    clock.advance(5)
    await rec.tick()  # a recheck
    assert rec.gaps["e1:yes_set"].reads == 2
    venue.price("y11", ask=0.62, bid=0.40)
    clock.advance(5)
    await rec.tick()
    assert rec.gaps == {}
    gap = rows(tmp_path, "gaps")[0]
    assert gap["lifetime"] == 5 and gap["reason"] == "closed"
    assert gap["peak_max_profit"] == pytest.approx(10.0)
    assert gap["run_seconds"] == 5 and gap["reads"] == 2
    obs = observations(tmp_path)
    assert len(obs) == 2 and obs[0][1] == "e1:yes_set"
    assert obs[0][10] == [[[0.4, 100.0]], [[0.5, 100.0]]]


async def test_watch_reads_near_sets_every_watch_interval(tmp_path: Path) -> None:
    venue = Venue([event("e1")])
    clock = Clock(NOW)
    venue.price("y10", ask=0.49, bid=0.30)
    venue.price("y11", ask=0.52, bid=0.30)  # 1.01: watched, not open
    rec = await loaded(venue, tmp_path, clock, sweep=10_000)
    await rec.tick()
    assert rec.watched == {"e1:yes_set"} and rec.gaps == {}
    venue.price("y11", ask=0.45, bid=0.30)
    clock.advance(5)
    await rec.tick()  # the watch is not due yet
    assert rec.gaps == {}
    clock.advance(30)
    await rec.tick()
    assert list(rec.gaps) == ["e1:yes_set"]
    venue.price("y10", ask=0.90, bid=0.30)
    clock.advance(5)
    await rec.tick()
    assert rec.gaps == {} and rec.watched == set()


async def test_a_missing_book_or_a_set_gone_closes_the_gap(tmp_path: Path) -> None:
    venue = Venue([event("e1"), event("e2")])
    clock = Clock(NOW)
    for token in ("y10", "y11", "y20", "y21"):
        venue.price(token, ask=0.40)
    rec = await loaded(venue, tmp_path, clock, catalogue=60)
    await rec.tick()
    assert sorted(rec.gaps) == ["e1:yes_set", "e2:yes_set"]
    venue.missing.add("y10")
    clock.advance(5)
    await rec.tick()
    assert list(rec.gaps) == ["e2:yes_set"]
    venue.events = [event("e1")]
    clock.advance(60)
    await rec.tick()  # a new catalogue pass starts
    assert rec.loading is not None
    await rec.loading
    clock.advance(5)
    await rec.tick()  # and is installed
    assert rec.gaps == {} and set(rec.sets) == {"e1:yes_set", "e1:no_set"}
    reasons = [g["reason"] for g in rows(tmp_path, "gaps")]
    assert reasons == ["no_book", "gone"]
    assert len(rows(tmp_path, "catalogue")) == 2


async def test_a_sweep_is_read_in_slices(tmp_path: Path) -> None:
    venue = Venue([event("e1"), event("e2"), event("e3")])
    clock = Clock(NOW)
    rec = await loaded(venue, tmp_path, clock, sweep_tokens=4)
    await rec.tick()
    assert len(rec.sweep_left) == 4  # 2 of 6 sets (4 tokens) a tick
    clock.advance(5)
    await rec.tick()
    clock.advance(5)
    await rec.tick()
    assert rec.sweep_left == []
    sweep = rows(tmp_path, "sweeps")[0]
    assert sweep["sets"] == 6 and sweep["missing"] == 6  # no books at all
    assert sweep["seconds"] == 10
    clock.advance(5)
    await rec.tick()  # the next sweep is not due
    assert rec.sweep_left == []


async def test_nothing_is_swept_before_a_catalogue(tmp_path: Path) -> None:
    venue = Venue([event("e1")])
    rec = recorder(venue, tmp_path, Clock(NOW))
    await rec.sweep_step(NOW)
    await rec.watch_step(NOW)
    await rec.recheck_step()
    assert rec.sweep_left == [] and venue.transport.count("/books") == 0
    assert rec.judge(["unknown"], {}) == 0


async def test_a_failed_catalogue_is_reported_and_retried(tmp_path: Path) -> None:
    venue = Venue([])
    venue.transport.routes["/events/keyset"] = HttpError("down", status=503)
    clock = Clock(NOW)
    rec = recorder(venue, tmp_path, clock)
    await rec.catalogue_step(NOW)
    assert rec.loading is not None
    await asyncio.gather(rec.loading, return_exceptions=True)
    await rec.catalogue_step(NOW)
    assert rec.errors == 1 and rec.failure.startswith("catalogue failed")
    assert rec.due["catalogue"] == NOW + 60
    assert rec.loading is None


async def test_stop_writes_open_gaps_censored_and_drops_a_pending_pass(
    tmp_path: Path,
) -> None:
    venue = Venue([event("e1")])
    clock = Clock(NOW)
    venue.price("y10", ask=0.40)
    venue.price("y11", ask=0.40)
    rec = await loaded(venue, tmp_path, clock, catalogue=1)
    clock.advance(1)
    await rec.tick()  # opens a gap and starts the next pass
    assert rec.gaps and rec.loading is not None
    await rec.stop()
    gap = rows(tmp_path, "gaps")[0]
    assert gap["censored"] and gap["reason"] == "stopped"
    assert rec.loading is None
    await rec.stop()  # nothing left


async def test_record_ticks_until_the_hours_pass_and_logs_failures(
    tmp_path: Path,
) -> None:
    venue = Venue([event("e1")])
    venue.price("y10", ask=0.40)
    venue.price("y11", ask=0.40)
    clock = Clock(NOW)
    calls = {"n": 0}
    original = venue.transport.routes["/books"]

    def flaky(url: str) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            return HttpError("busy", status=503)
        return original(url)

    venue.transport.routes["/books"] = flaky
    logged: list[str] = []

    async def sleep(seconds: float) -> None:
        await asyncio.sleep(0)
        clock.advance(max(seconds, 1.0))

    counts = await record(
        venue.gamma,
        venue.clob,
        directory=tmp_path,
        hours=60 / 3600,
        clock=clock,
        sleep=sleep,
        log=logged.append,
    )
    assert counts["catalogue"] == 1 and counts["gaps"] == 1
    assert any("tick failed" in line for line in logged)
    assert any(line.startswith("catalogue: 1 neg-risk events") for line in logged)
    assert any(line.startswith("sweep: 2 sets") for line in logged)
    gaps = rows(tmp_path, "gaps")
    assert gaps[-1]["kind"] == KIND_YES


async def test_record_logs_a_failed_catalogue(tmp_path: Path) -> None:
    venue = Venue([])
    venue.transport.routes["/events/keyset"] = HttpError("down", status=503)
    clock = Clock(NOW)
    logged: list[str] = []

    async def sleep(seconds: float) -> None:
        await asyncio.sleep(0)
        clock.advance(seconds)

    await record(
        venue.gamma,
        venue.clob,
        directory=tmp_path,
        hours=20 / 3600,
        clock=clock,
        sleep=sleep,
        log=logged.append,
    )
    assert any("catalogue failed" in line for line in logged)
