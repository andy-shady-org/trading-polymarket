from __future__ import annotations

import pytest

from trading_polymarket.clients.weather import (
    Forecast,
    PreviousRuns,
    WeatherClient,
    _model_series,
    metar_temperature,
)
from trading_polymarket.tests.support.factories import (
    NOW,
    fixture,
    forecast_payload,
    metar_row,
)
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("METAR KDAL 280753Z 15008KT 10SM CLR 19/14 A3014 RMK AO2 T01940144", 19.4),
        ("METAR KDAL 280753Z 15008KT 10SM CLR M01/M03 A3014 RMK AO2 T10171022", -1.7),
        ("METAR RJTT 280830Z 35015KT 9999 FEW030 16/02 Q1019 NOSIG", 16.0),
        ("METAR UUEE 280830Z 35015KT 9999 M11/M17 Q1019", -11.0),
        ("METAR XXXX 280830Z 35015KT 1/2SM FG Q1019", None),
        ("METAR XXXX 280830Z 35015KT 9999 16/ Q1019", 16.0),
        ("METAR XXXX 280830Z 9999 16/02 RMK NO T GROUP", 16.0),
    ],
)
def test_metar_temperature(raw: str, expected: float | None) -> None:
    assert metar_temperature(raw) == expected


def client(transport: FakeTransport) -> WeatherClient:
    return WeatherClient(
        fake_http(transport),
        awc_url="https://awc.test",
        open_meteo_url="https://om.test",
        ensemble_url="https://ens.test",
        previous_runs_url="https://prev.test",
    )


async def test_metars_parse_sort_and_flag_speci() -> None:
    rows = [
        metar_row(NOW, kind="SPECI"),
        metar_row(NOW - 3600, raw="METAR KDAL 281153Z 17/14 RMK T01720144"),
        metar_row(NOW - 60, raw="SPECI KDAL 281159Z 18/14", kind=""),
        {"icaoId": "KDAL", "obsTime": "x"},
        "junk",
    ]
    found = await client(FakeTransport({"/api/data/metar": rows})).metars("KDAL")
    assert [m.obs_time for m in found] == [NOW - 3600, NOW - 60, NOW]
    assert found[0].temperature == 17.2 and found[0].routine
    assert not found[1].routine and not found[2].routine
    assert await client(FakeTransport({"/api/data/metar": {}})).metars("K") == []


async def test_real_metar_fixture() -> None:
    rows = fixture("metar.json")
    found = await client(FakeTransport({"/api/data/metar": rows})).metars("KDAL")
    assert found and all(m.temperature is not None for m in found)


async def test_station_lookup() -> None:
    rows = [
        {"icaoId": "X"},
        {"icaoId": "KDAL", "site": "Dallas", "lat": 32.8, "lon": -96.8, "elev": 148},
    ]
    station = await client(FakeTransport({"stationinfo": rows})).station("KDAL")
    assert station is not None and station.latitude == 32.8 and station.name == "Dallas"
    assert await client(FakeTransport({"stationinfo": []})).station("KDAL") is None
    assert await client(FakeTransport({"stationinfo": {}})).station("KDAL") is None


async def test_forecast_reads_models_and_zone() -> None:
    transport = FakeTransport({"/v1/forecast": forecast_payload()})
    forecast = await client(transport).forecast(
        32.8, -96.8, models=("ecmwf_ifs025", "gfs_seamless")
    )
    assert forecast.timezone == "America/Chicago"
    assert forecast.model_maxima("2026-10-28") == {
        "ecmwf_ifs025": 24.0,
        "gfs_seamless": 25.0,
    }
    assert forecast.model_maxima("2026-10-29") == {}
    assert forecast.remaining_max("ecmwf_ifs025", "2026-10-28", 16) == 23.5
    assert forecast.remaining_max("ecmwf_ifs025", "2026-10-28", 30) is None
    assert "models=ecmwf_ifs025%2Cgfs_seamless" in transport.calls[0]
    assert "past_days" not in transport.calls[0]
    bare = await client(FakeTransport({"/v1/forecast": {}})).forecast(1, 2, past_days=1)
    assert bare.timezone == "UTC" and bare.daily_max == {}


def test_model_series_single_model_without_suffix() -> None:
    block = {"time": ["a", "b"], "x": [1.0, None]}
    assert _model_series(block, "x", ["m"]) == {"m": {"a": 1.0}}
    assert _model_series({"time": ["a"], "x_m": "bad"}, "x", ["m"]) == {}


async def test_ensemble_maxima() -> None:
    payload = {
        "daily": {
            "time": ["2026-10-28", "2026-10-29"],
            "temperature_2m_max": [20.0, 21.0],
            "temperature_2m_max_member01": [19.0, None],
            "temperature_2m_max_member02": [21.0],
            "other": [1, 2],
        }
    }
    c = client(FakeTransport({"/v1/ensemble": payload}))
    assert await c.ensemble_maxima(1, 2, "2026-10-28") == [20.0, 19.0, 21.0]
    assert await c.ensemble_maxima(1, 2, "2026-10-29") == [21.0]
    assert await c.ensemble_maxima(1, 2, "2026-11-01") == []


async def test_previous_day_maxima() -> None:
    payload = {
        "timezone": "Europe/London",
        "utc_offset_seconds": 0,
        "hourly": {
            "time": ["2026-10-27T00:00", "2026-10-27T14:00", "2026-10-28T13:00"],
            "temperature_2m_previous_day1_a": [10.0, 14.0, 12.0],
            "temperature_2m_previous_day1_b": [11.0, 16.0, None],
        },
    }
    runs = await client(FakeTransport({"/v1/forecast": payload})).previous_day_maxima(
        1, 2, models=("a", "b")
    )
    assert runs.timezone == "Europe/London"
    assert runs.maxima == {
        "a": {"2026-10-27": 14.0, "2026-10-28": 12.0},
        "b": {"2026-10-27": 16.0},
    }
    assert runs.mean("2026-10-27") == 15.0
    assert runs.remaining_maxima("2026-10-27", 10) == [14.0, 16.0]
    assert runs.remaining_maxima("2026-10-27", 20) == []
    assert runs.mean("2026-10-28") == 12.0
    assert runs.mean("2026-10-30") is None
    empty = await client(FakeTransport({"/v1/forecast": {}})).previous_day_maxima(1, 2)
    assert empty == PreviousRuns("UTC", 0, {})


def test_forecast_defaults() -> None:
    assert Forecast("UTC", 0, {}).hourly == {}
