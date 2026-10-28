from __future__ import annotations

from pathlib import Path

from trading_polymarket.clients.weather import Metar, WeatherClient
from trading_polymarket.research.metar_archive import (
    archive,
    load_archive,
    load_station,
    merge,
)
from trading_polymarket.research.records import append_jsonl
from trading_polymarket.tests.support.factories import NOW, metar_row
from trading_polymarket.tests.support.fakes import FakeTransport, Sequenced, fake_http


def m(t: float, temp: float = 10.0) -> Metar:
    return Metar("KDAL", t, temp, "raw")


def test_merge_dedupes_and_sorts() -> None:
    merged = merge({"KDAL": [m(2), m(1)]}, {"KDAL": [m(2, 99.0), m(3)], "X": []})
    assert [x.obs_time for x in merged["KDAL"]] == [1, 2, 3]
    assert merged["KDAL"][1].temperature == 10.0  # first source wins
    assert merged["X"] == []


def test_load_station_and_archive(tmp_path: Path) -> None:
    assert load_archive(tmp_path / "none") == {}
    append_jsonl(
        tmp_path / "KDAL.jsonl",
        [
            {"icao": "KDAL", "obs_time": 5, "temperature": 1, "raw": "r"},
            {"bad": 1},
            {"icao": "KDAL", "obs_time": 2, "temperature": 1, "raw": "r"},
        ],
    )
    assert [x.obs_time for x in load_station(tmp_path, "KDAL")] == [2, 5]
    assert list(load_archive(tmp_path)) == ["KDAL"]


async def test_archive_appends_only_new_reports(tmp_path: Path) -> None:
    transport = FakeTransport(
        {
            "ids=KDAL": Sequenced(
                [metar_row(NOW - 3600)], [metar_row(NOW - 3600), metar_row(NOW)]
            ),
            "ids=KBAD": OSError("down"),
        }
    )
    client = WeatherClient(fake_http(transport, max_retries=0))
    lines: list[str] = []
    assert await archive(client, ["KDAL", "KBAD"], directory=tmp_path) == 1
    assert (
        await archive(
            client, ["KDAL", "KBAD"], directory=tmp_path, progress=lines.append
        )
        == 1
    )
    assert [x.obs_time for x in load_station(tmp_path, "KDAL")] == [NOW - 3600, NOW]
    assert lines and "KBAD" in lines[0]
