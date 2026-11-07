"""Unit tests for ``research/lane_rows.py``: collected data as library rows
(FEAT-149)."""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from trading_core.lanes.market import Listing, Outcome, Reading, TradePrint
from trading_core.lanes.sweep import load_capture

from trading_polymarket.research import lane_rows as lr
from trading_polymarket.research.updown import UpDownMarket, day_path
from trading_polymarket.tests.support.factories import NOW, history_row

END = NOW
HOUR = 3600.0


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def _write(tmp_path: Path, request: lr.LaneRowsRequest, name: str = "rows.jsonl"):
    out = tmp_path / name
    stats = lr.write_lane_rows(request, out)
    return stats, load_capture([out])


def _by(records: list[Any], kind: type, instrument: str) -> list[Any]:
    return [
        r
        for r in records
        if isinstance(r, kind) and getattr(r, "instrument_id", None) == instrument
    ]


def test_history_writes_both_tokens_and_their_settlement(tmp_path: Path) -> None:
    prices = [
        (END - 3 * HOUR, 0.4),
        (END - 2 * HOUR, 0.0),  # no price: skipped on the first token
        (END - HOUR, 0.6),
        (END, 0.7),  # at the end: skipped
    ]
    source = _jsonl(
        tmp_path / "markets.jsonl",
        [
            history_row(market_id="1", winner=1, prices=prices, fee_rate=0.04),
            history_row(market_id="2", fee_rate=0.0),
            {**history_row(market_id="3", fee_rate=0.04), "history": []},
        ],
    )
    request = lr.LaneRowsRequest(lr.SOURCE_HISTORY, source, fee_rate=0.04)
    stats, records = _write(tmp_path, request)
    first, second = "11111111", "12121212"
    listing = _by(records, Listing, first)[0]
    assert listing.at == END - 3 * HOUR and listing.resolves_at == END
    assert listing.kind == lr.KIND_MARKET
    assert [r.price for r in _by(records, Reading, first)] == [0.4, 0.6]
    assert [r.price for r in _by(records, Reading, second)] == [0.6, 1.0, 0.4]
    assert _by(records, Outcome, first)[0].value == 0.0
    assert _by(records, Outcome, second)[0].value == 1.0
    assert stats.markets == 2 and stats.fee_rates == {0.04: 2, 0.0: 1}
    assert stats.skipped == {
        lr.SKIP_PRICE: 1,
        lr.SKIP_AFTER_END: 2,
        lr.SKIP_FEE: 1,
        lr.SKIP_EMPTY: 2,
    }
    assert stats.rows == {"listing": 2, "reading": 5, "outcome": 2}


def test_weather_writes_yes_and_no_of_every_bucket(tmp_path: Path) -> None:
    event = {
        "event_id": "9",
        "city": "London",
        "icao": "EGLC",
        "unit": "C",
        "day": "2026-10-23",
        "end_time": END,
        "buckets": [
            {
                "low": None,
                "high": 9,
                "yes_token": "y9",
                "no_token": "n9",
                "won": True,
                "history": [[END - HOUR, 0.3]],
                "fee_rate": 0.0,
            },
            {
                "low": 10,
                "high": None,
                "yes_token": "y10",
                "no_token": "n10",
                "won": False,
                "history": [[END - HOUR, 0.7]],
            },
        ],
    }
    source = _jsonl(tmp_path / "weather.jsonl", [event])
    stats, records = _write(tmp_path, lr.LaneRowsRequest(lr.SOURCE_WEATHER, source))
    assert _by(records, Reading, "n9")[0].price == pytest.approx(0.7)
    assert [_by(records, Outcome, i)[0].value for i in ("y9", "n9", "y10", "n10")] == [
        1.0,
        0.0,
        0.0,
        1.0,
    ]
    assert stats.markets == 2 and stats.rows["listing"] == 4


def test_fed_readings_carry_kalshis_last_closed_mid(tmp_path: Path) -> None:
    close = END
    bucket = {
        "bucket": "hold",
        "code": "H0",
        "yes_token": "yes",
        "no_token": "no",
        "kalshi_ticker": "KX-H0",
        "won": True,
        "kalshi_won": True,
        "fee_rate": 0.0,
        "pm": [[close - 3 * HOUR, 0.6], [close - HOUR, 0.7], [close + HOUR, 0.9]],
        "kalshi": [[close - 2 * HOUR, 0.64, 0.68, 10], [close - HOUR, None, 0.7, 1]],
    }
    meeting = {
        "event_id": "1",
        "title": "Fed",
        "kalshi_event": "KX",
        "close_time": close,
        "buckets": [bucket],
    }
    source = _jsonl(tmp_path / "fed.jsonl", [meeting])
    stats, records = _write(tmp_path, lr.LaneRowsRequest(lr.SOURCE_FED, source))
    yes = _by(records, Reading, "yes")
    # Before the first candle ended: no reference; at close - 1 h the last
    # candle that ended (that hour's) has no bid, so no mid either.
    assert [r.reference for r in yes] == [None, None]
    assert stats.skipped == {lr.SKIP_AFTER_END: 2}
    early = {**bucket, "pm": [[close - 1.5 * HOUR, 0.6]]}
    source = _jsonl(tmp_path / "fed2.jsonl", [{**meeting, "buckets": [early]}])
    _, records = _write(
        tmp_path, lr.LaneRowsRequest(lr.SOURCE_FED, source), name="rows2.jsonl"
    )
    assert _by(records, Reading, "yes")[0].reference == pytest.approx(0.66)
    no = _by(records, Reading, "no")[0]
    assert no.price == pytest.approx(0.4) and no.reference == pytest.approx(0.34)
    assert _by(records, Outcome, "no")[0].value == 0.0


def _updown(tmp_path: Path) -> Path:
    start = END - 300
    market = UpDownMarket(
        slug="btc-updown-5m-1",
        condition_id="0xc",
        start=start,
        end=END,
        winner=1,
        price_to_beat=1.0,
        final_price=0.9,
        fee_rate=0.07,
        volume=100.0,
        trades=(
            (10.0, 0, 1, 0.5, 20.0, "0xw"),
            (20.0, 1, -1, 0.4, 10.0, ""),
            (299.5, 1, 1, 0.6, 5.0, "0xw"),  # past the end once shifted
            (30.0, 0, 1, 1.5, 5.0, "0xw"),  # not a price
        ),
    )
    path = day_path(tmp_path, "btc", "5m", date(2026, 10, 28))
    path.parent.mkdir(parents=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(market.to_dict()) + "\n")
    return tmp_path


def test_updown_writes_each_side_with_its_prints(tmp_path: Path) -> None:
    folder = _updown(tmp_path)
    request = lr.LaneRowsRequest(lr.SOURCE_UPDOWN, folder, print_offset=1.0)
    stats, records = _write(tmp_path, request)
    up, down = "0xc:up", "0xc:down"
    assert _by(records, Listing, up)[0].at == END - 300
    assert [r.at for r in _by(records, Reading, up)] == [END - 289]
    print_up = _by(records, TradePrint, up)[0]
    assert (print_up.wallet, print_up.side, print_up.amount) == ("0xw", "buy", 10.0)
    print_down = _by(records, TradePrint, down)[0]
    assert (print_down.wallet, print_down.side) == (None, "sell")
    assert print_down.amount == pytest.approx(4.0)
    assert [_by(records, Outcome, i)[0].value for i in (up, down)] == [0.0, 1.0]
    assert stats.skipped == {lr.SKIP_PRINT: 2} and stats.fee_rates == {0.07: 1}
    later = lr.LaneRowsRequest(
        lr.SOURCE_UPDOWN, folder, start=date(2026, 10, 29), fee_rate=0.07
    )
    stats, records = _write(tmp_path, later, name="none.jsonl.gz")
    assert records == [] and stats.markets == 0
    assert lr.describe(stats) == [
        "0 markets written: no rows",
        "markets by fee rate: none",
    ]


def test_describe_counts_rows_rates_and_skips(tmp_path: Path) -> None:
    stats, _ = _write(tmp_path, lr.LaneRowsRequest(lr.SOURCE_UPDOWN, _updown(tmp_path)))
    assert lr.describe(stats) == [
        "1 markets written: 2 listing, 2 outcome, 3 reading, 3 trade",
        "markets by fee rate: 0.07: 1",
        f"skipped 1: {lr.SKIP_PRINT}",
    ]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"source": "ticks"}, "unknown source 'ticks'"),
        ({"fee_rate": 1.0}, "fee_rate must be within"),
        ({"print_offset": float("nan")}, "print_offset must be a number"),
    ],
)
def test_a_request_is_checked(changes: dict[str, Any], message: str) -> None:
    values: dict[str, Any] = {"source": lr.SOURCE_HISTORY, "input": "x"}
    with pytest.raises(ValueError, match=message):
        lr.LaneRowsRequest(**{**values, **changes})


def test_the_output_is_new_and_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _jsonl(tmp_path / "markets.jsonl", [history_row()])
    request = lr.LaneRowsRequest(lr.SOURCE_HISTORY, source)
    with pytest.raises(ValueError, match="must end in .jsonl"):
        lr.write_lane_rows(request, tmp_path / "rows.csv")
    taken = _jsonl(tmp_path / "taken.jsonl", [])
    with pytest.raises(ValueError, match="exists already"):
        lr.write_lane_rows(request, taken)
    with pytest.raises(ValueError, match="no such file"):
        lr.write_lane_rows(
            lr.LaneRowsRequest(lr.SOURCE_HISTORY, tmp_path / "gone"),
            tmp_path / "a.jsonl",
        )
    with pytest.raises(ValueError, match="no updown-history collection"):
        lr.write_lane_rows(
            lr.LaneRowsRequest(lr.SOURCE_UPDOWN, tmp_path), tmp_path / "b.jsonl"
        )

    def broken(*_: Any) -> Any:
        raise RuntimeError("disk full")

    monkeypatch.setattr(lr, "lane_records", broken)
    with pytest.raises(RuntimeError, match="disk full"):
        lr.write_lane_rows(request, tmp_path / "c.jsonl.gz")
    assert not list(tmp_path.glob("c.jsonl.gz*"))


def test_every_source_keeps_only_the_fee_rate_asked_for(tmp_path: Path) -> None:
    weather = _jsonl(
        tmp_path / "weather.jsonl",
        [
            {
                "event_id": "9",
                "city": "London",
                "icao": "EGLC",
                "unit": "C",
                "day": "2026-10-23",
                "end_time": END,
                "buckets": [
                    {
                        "low": 9,
                        "high": 9,
                        "yes_token": "y",
                        "no_token": "n",
                        "won": True,
                        "history": [[END - HOUR, 0.3]],
                    }
                ],
            }
        ],
    )
    fed = _jsonl(
        tmp_path / "fed.jsonl",
        [
            {
                "event_id": "1",
                "title": "Fed",
                "kalshi_event": "KX",
                "close_time": END,
                "buckets": [
                    {
                        "bucket": "hold",
                        "code": "H0",
                        "yes_token": "y",
                        "no_token": "n",
                        "kalshi_ticker": "KX-H0",
                        "won": True,
                        "kalshi_won": True,
                        "pm": [[END - HOUR, 0.6]],
                        "kalshi": [],
                    }
                ],
            }
        ],
    )
    sources = [
        (lr.SOURCE_WEATHER, weather),
        (lr.SOURCE_FED, fed),
        (lr.SOURCE_UPDOWN, _updown(tmp_path / "updown")),
    ]
    for index, (source, path) in enumerate(sources):
        request = lr.LaneRowsRequest(source, path, fee_rate=0.5)
        stats, records = _write(tmp_path, request, name=f"{index}.jsonl")
        assert records == [] and stats.skipped == {lr.SKIP_FEE: 1}
