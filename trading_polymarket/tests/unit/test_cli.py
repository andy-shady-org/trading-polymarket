from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from trading_polymarket import cli
from trading_polymarket.module import PolymarketModule
from trading_polymarket.research.records import append_jsonl
from trading_polymarket.tests.support.factories import (
    NOW,
    book_payload,
    forecast_payload,
    gamma_market,
    history_row,
    metar_row,
    weather_event,
)
from trading_polymarket.tests.support.fakes import Clock, FakeTransport, fake_http

STATIONS = {"KDAL": {"lat": 32.8, "lon": -96.8}}


def routes(**extra: Any) -> FakeTransport:
    table: dict[str, Any] = {
        "/events/keyset": {"events": [weather_event()]},
        "/markets/keyset": {"markets": []},
        "/v1/forecast": forecast_payload(),
        "/api/data/metar": [metar_row(NOW - 3600)],
        "/book": book_payload(bids=[(0.08, 500)], asks=[(0.10, 500)]),
        "/prices-history": {"history": []},
    }
    table.update(extra)
    return FakeTransport(table)


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> FakeTransport:
    fake = routes()
    monkeypatch.setattr(
        cli,
        "PolymarketModule",
        partial(
            PolymarketModule,
            http=fake_http(fake, max_retries=0),
            clock=Clock(NOW),
            stations=STATIONS,
        ),
    )
    monkeypatch.setattr(cli, "load_stations", lambda: STATIONS)
    return fake


def run(*argv: str) -> tuple[int, list[str]]:
    lines: list[str] = []
    return cli.main(list(argv), out=lines.append), lines


def config(tmp_path: Path, settings: dict[str, Any]) -> str:
    path = tmp_path / "paper.json"
    path.write_text(json.dumps({"module": "polymarket", "module_settings": settings}))
    return str(path)


def test_module_settings(tmp_path: Path) -> None:
    assert cli.module_settings(None) == {}
    assert cli.module_settings(config(tmp_path, {"bankroll": 5})) == {"bankroll": 5}
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"module_settings": []}))
    with pytest.raises(ValueError):
        cli.module_settings(str(bad))
    bad.write_text("[]")
    assert cli.module_settings(str(bad)) == {}


def test_scan_prints_signals(transport: FakeTransport, tmp_path: Path) -> None:
    models = {"weather": {"models": ["ecmwf_ifs025", "gfs_seamless"]}}
    code, lines = run("scan", "--config", config(tmp_path, models))
    assert code == 0 and lines[0].startswith("pipeline: weather-events")
    assert any(line.startswith("weather ") for line in lines)
    code, lines = run("scan", "--lane", "momentum", "--limit", "1")
    assert code == 0 and "0 signals" in lines[1]


def test_scan_without_lanes(transport: FakeTransport, tmp_path: Path) -> None:
    code, lines = run(
        "scan", "--config", config(tmp_path, {"weather": {"enabled": False}})
    )
    assert code == 1 and lines == ["no lane is enabled"]


def test_scan_reports_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = routes(**{"/events/keyset": OSError("down")})
    monkeypatch.setattr(
        cli,
        "PolymarketModule",
        partial(PolymarketModule, http=fake_http(broken, max_retries=0)),
    )
    code, lines = run("scan")
    assert code == 0 and any(line.startswith("error: scout") for line in lines)


def test_weather_lists_model_and_market(transport: FakeTransport) -> None:
    code, lines = run("weather", "--city", "Dallas")
    assert code == 0
    assert any("KDAL" in line for line in lines)
    assert any("74-75°F" in line and "model" in line for line in lines)
    assert run("weather", "--city", "London")[1] == []


def test_weather_skips_unknown_and_far_events(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = routes(
        **{
            "/events/keyset": {
                "events": [weather_event(day="November 9"), {"title": "x"}]
            }
        }
    )
    monkeypatch.setattr(
        cli,
        "PolymarketModule",
        partial(
            PolymarketModule, http=fake_http(fake), clock=Clock(NOW), stations=STATIONS
        ),
    )
    assert run("weather") == (0, [])
    blank = weather_event()
    blank["markets"][0].update(bestAsk=None, bestBid=None)
    fake = routes(**{"/events/keyset": {"events": [blank]}})
    monkeypatch.setattr(
        cli,
        "PolymarketModule",
        partial(
            PolymarketModule, http=fake_http(fake), clock=Clock(NOW), stations=STATIONS
        ),
    )
    code, lines = run("weather")
    assert code == 0 and any(" - " in line or "-" in line for line in lines[1:])


def test_record(transport: FakeTransport, tmp_path: Path) -> None:
    code, lines = run("record", "--cycles", "1", "--out", str(tmp_path / "rec"))
    assert code == 0 and "recorded" in lines[-1]
    assert (tmp_path / "rec" / "2026-10-28.jsonl").is_file()


def test_arb(
    transport: FakeTransport, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pair = gamma_market(bestAsk=0.48, bestBid=0.53, feeSchedule=None, feesEnabled=False)
    fake = routes(
        **{
            "/events/keyset": {
                "events": [
                    {"title": "Pair", "negRiskAugmented": True, "markets": [pair]}
                ]
            },
            "/book": book_payload(asks=[(0.47, 100)]),
        }
    )
    monkeypatch.setattr(
        cli, "PolymarketModule", partial(PolymarketModule, http=fake_http(fake))
    )
    out = tmp_path / "arb.jsonl"
    code, lines = run("arb", "--out", str(out))
    assert code == 0 and lines[0].startswith("binary_pair")
    assert out.is_file() and "1 opportunities" in lines[-1]


def test_bias(transport: FakeTransport, tmp_path: Path) -> None:
    out = tmp_path / "bias.json"
    code, lines = run("bias", "--station", "KDAL", "--days", "3", "--out", str(out))
    assert code == 0 and out.is_file() and "written" in lines[-1]
    code, _ = run("bias", "--station", "NONE", "--out", str(out))
    assert code == 0
    code, _ = run("bias", "--days", "1", "--out", str(out))
    assert code == 0


def test_metars(transport: FakeTransport, tmp_path: Path) -> None:
    code, lines = run("metars", "--out", str(tmp_path / "m"))
    assert code == 0 and lines[-1].startswith("1 new METARs")


def test_history_and_weather_history(transport: FakeTransport, tmp_path: Path) -> None:
    code, lines = run(
        "history",
        "--start",
        "2026-10-01",
        "--end",
        "2026-10-04",
        "--out",
        str(tmp_path / "h.jsonl"),
    )
    assert code == 0 and lines[-1].startswith("0 markets")
    code, lines = run(
        "weather-history",
        "--start",
        "2026-10-01",
        "--end",
        "2026-10-04",
        "--out",
        str(tmp_path / "w.jsonl"),
    )
    assert code == 0 and lines[-1].startswith("0 events")


def write_history(tmp_path: Path) -> Path:
    path = tmp_path / "h.jsonl"
    rows = []
    for i in range(40):
        end = NOW - (40 - i) * 86400
        rows.append(
            history_row(
                market_id=str(i),
                winner=0 if i % 10 else 1,
                end_time=end,
                prices=[(end - 80 * 3600, 0.88), (end - 3600, 0.95)],
            )
        )
    append_jsonl(path, rows)
    return path


def test_calibrate(tmp_path: Path) -> None:
    assert cli.main(["calibrate", "--input", str(tmp_path / "none")], out=print) == 1
    history = write_history(tmp_path)
    out = tmp_path / "cal.json"
    lines: list[str] = []
    code = cli.main(
        ["calibrate", "--input", str(history), "--out", str(out)], out=lines.append
    )
    assert code == 0 and out.is_file() and "trained on 28 markets" in lines[0]
    lines = []
    cli.main(
        [
            "calibrate",
            "--input",
            str(history),
            "--all",
            "--split",
            "2026-10-01",
            "--out",
            str(out),
        ],
        out=lines.append,
    )
    assert "trained on 40 markets (test set: 0)" in lines[0]


def test_backtest_favourite(tmp_path: Path) -> None:
    assert run("backtest", "favourite", "--input", str(tmp_path / "none"))[0] == 1
    history = write_history(tmp_path)
    out = tmp_path / "fav.jsonl"
    out.write_text("old\n")
    code, lines = run(
        "backtest",
        "favourite",
        "--input",
        str(history),
        "--split",
        "2026-10-15",
        "--out",
        str(out),
    )
    assert code == 0 and "trading-core-audit verdict" in lines[-1]
    assert json.loads(lines[0])["markets"] == 13
    assert "old" not in out.read_text()


def test_backtest_weather(transport: FakeTransport, tmp_path: Path) -> None:
    assert run("backtest", "weather", "--input", str(tmp_path / "none"))[0] == 1
    path = tmp_path / "w.jsonl"
    append_jsonl(
        path,
        [
            {
                "event_id": "1",
                "city": "Dallas",
                "icao": "KDAL",
                "unit": "F",
                "day": "2026-10-20",
                "end_time": NOW,
                "buckets": [
                    {
                        "low": None,
                        "high": 80,
                        "yes_token": "y",
                        "no_token": "n",
                        "won": True,
                        "history": [[NOW - 9e6, 0.5]],
                    }
                ],
            }
        ],
    )
    code, lines = run(
        "backtest", "weather", "--input", str(path), "--out", str(tmp_path / "o.jsonl")
    )
    assert code == 0 and json.loads(lines[0])["markets"] in (0, 1)
    code, lines = run(
        "backtest",
        "weather",
        "--input",
        str(path),
        "--intraday",
        "--entry-hour",
        "16",
        "--out",
        str(tmp_path / "o.jsonl"),
    )
    assert code == 0 and json.loads(lines[-3])["markets"] == 0


def test_errors_are_reported_not_raised(
    transport: FakeTransport, tmp_path: Path
) -> None:
    code, lines = run("scan", "--config", str(tmp_path / "missing.json"))
    assert code == 2 and lines[0].startswith("error:")
    code, lines = run("fed-history", "--out", str(tmp_path / "f.jsonl"))
    assert code == 2 and lines[-1] == "error: HTTP 404"  # unrouted public search


def test_a_closed_pipe_is_not_an_error(tmp_path: Path) -> None:
    def closed(line: str) -> None:
        raise BrokenPipeError

    history = write_history(tmp_path)
    assert cli.main(["calibrate", "--input", str(history)], out=closed) == 0


def test_parser_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_fed_history_and_backtest(transport: FakeTransport, tmp_path: Path) -> None:
    out = tmp_path / "fed.jsonl"
    transport.add("/public-search", {"events": []}).add("/events?", {"events": []})
    code, lines = run("fed-history", "--out", str(out), "--days", "1")
    assert code == 0 and lines[-1] == f"0 meetings appended to {out}"
    assert transport.count("/public-search") == 1
    assert run("backtest", "fed", "--input", str(tmp_path / "none"))[0] == 1
    close = NOW
    meeting = {
        "event_id": "1",
        "title": "Fed Decision in November?",
        "kalshi_event": "KXFEDDECISION-26NOV",
        "close_time": close,
        "buckets": [
            {
                "bucket": "No change",
                "code": "H0",
                "yes_token": "y",
                "no_token": "n",
                "kalshi_ticker": "KXFEDDECISION-26NOV-H0",
                "won": True,
                "kalshi_won": True,
                "pm": [[close - 36000, 0.55]],
                "kalshi": [
                    [close - h * 3600, 0.6, 0.62, 1000] for h in range(10, 0, -1)
                ],
            }
        ],
    }
    append_jsonl(tmp_path / "m.jsonl", [meeting])
    code, lines = run(
        "backtest", "fed", "--input", str(tmp_path / "m.jsonl"), "--out", str(out)
    )
    summary = json.loads(lines[0])
    assert code == 0 and summary["trades"] == 1 and "1h" in summary["scores"]
    assert "configs/verdict/fed.json" in lines[-1]


def test_pairs_commands(transport: FakeTransport, tmp_path: Path) -> None:
    pairs = str(tmp_path / "pairs.json")
    transport.add(
        "/events?",
        {
            "events": [
                {
                    "event_ticker": "K",
                    "markets": [
                        {
                            "ticker": "KX-ALICE",
                            "title": "Highest temperature in Dallas 74-75°F?",
                            "yes_sub_title": "",
                            "close_time": "2026-10-28T12:00:00Z",
                        }
                    ],
                }
            ]
        },
    )
    suggested = str(tmp_path / "s.jsonl")
    code, lines = run("pairs", "suggest", "--out", suggested, "--pages", "1")
    assert code == 0 and "candidates written" in lines[-2]
    assert any("KX-ALICE" in line for line in lines)
    assert run("pairs", "approve", "--pairs", pairs)[0] == 2
    code, lines = run(
        "pairs",
        "approve",
        "tok1",
        "KX-1",
        "--side",
        "no",
        "--label",
        "A",
        "--pairs",
        pairs,
    )
    assert code == 0 and lines[-1] == f"1 pairs in {pairs}"
    run("pairs", "approve", "tok2", "KX-2", "--pairs", pairs)
    code, lines = run("pairs", "list", "--pairs", pairs)
    assert lines[0].startswith("tok1…") and "(no) A" in lines[0]
    assert lines[-1] == f"2 pairs in {pairs}"
    code, lines = run("pairs", "remove", "tok1", "--pairs", pairs)
    assert lines[-1] == f"1 removed; 1 pairs in {pairs}"
    settings = config(tmp_path, {"crossvenue": {"pairs_path": pairs}})
    assert run("pairs", "list", "--config", settings)[1][-1] == f"1 pairs in {pairs}"
