from __future__ import annotations

from datetime import date, timedelta, timezone
from typing import Any

import pytest

from trading_polymarket.catalogue import BookCache, MarketCatalogue
from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.weather import Forecast, WeatherClient
from trading_polymarket.config import WeatherLane
from trading_polymarket.markets import Market, markets_from_event
from trading_polymarket.strategies.common import KEY_FAIR, KEY_MARKET
from trading_polymarket.strategies.weather import (
    Bucket,
    TempDistribution,
    WeatherAnalyst,
    WeatherEvent,
    WeatherModel,
    WeatherScout,
    applied_bias,
    blend,
    lead_sigma,
    load_bias,
    load_stations,
    normal_cdf,
    round_half_up,
    station_zone,
    to_celsius,
    to_unit,
)
from trading_polymarket.tests.support.factories import (
    NOW,
    book_payload,
    fixture,
    forecast_payload,
    market,
    metar_row,
    weather_event,
)
from trading_polymarket.tests.support.fakes import Clock, FakeTransport, fake_http

STATIONS = {"KDAL": {"lat": 32.8, "lon": -96.8, "name": "Dallas"}}
LANE = WeatherLane(models=("ecmwf_ifs025", "gfs_seamless"))


def parsed(**kwargs: Any) -> WeatherEvent:
    raw = weather_event(**kwargs)
    event = WeatherEvent.parse(raw, markets_from_event(raw))
    assert event is not None
    return event


def weather_routes(**extra: Any) -> FakeTransport:
    routes = {
        "/v1/forecast": forecast_payload(),
        "/api/data/metar": [metar_row(NOW - 3600)],
        "stationinfo": [{"icaoId": "KXXX", "lat": 1, "lon": 2, "site": "X"}],
    }
    routes.update(extra)
    return FakeTransport(routes)


def model(
    transport: FakeTransport | None = None,
    lane: WeatherLane = LANE,
    clock: Clock | None = None,
    **kwargs: Any,
) -> WeatherModel:
    client = WeatherClient(fake_http(transport or weather_routes(), max_retries=0))
    return WeatherModel(
        client,
        lane,
        stations=kwargs.pop("stations", STATIONS),
        bias=kwargs.pop("bias", {}),
        clock=clock or Clock(NOW),
    )


# -- pure helpers ----------------------------------------------------------
def test_units_rounding_and_cdf() -> None:
    assert round_half_up(16.5) == 17 and round_half_up(-8.5) == -8
    assert to_unit(18.3, "F") == pytest.approx(64.94) and to_unit(5, "C") == 5
    assert to_celsius(64.94, "F") == pytest.approx(18.3) and to_celsius(5, "C") == 5
    assert normal_cdf(0) == 0.5
    assert blend(0.8, 0.4, 0.5) == pytest.approx(0.6) and blend(0.8, None, 0.5) == 0.8


@pytest.mark.parametrize(
    ("title", "low", "high", "unit", "label"),
    [
        ("74-75°F", 74, 75, "F", "74-75°F"),
        ("73°F or below", None, 73, "F", "<=73°F"),
        ("14°C or lower", None, 14, "C", "<=14°C"),
        ("92°F or higher", 92, None, "F", ">=92°F"),
        ("24ºC or above", 24, None, "C", ">=24°C"),
        ("15°C", 15, 15, "C", "15°C"),
        ("-3--1°C", -3, -1, "C", "-3--1°C"),
    ],
)
def test_bucket_parse(
    title: str, low: int | None, high: int | None, unit: str, label: str
) -> None:
    bucket = Bucket.parse(title, market())
    assert bucket is not None
    assert (bucket.low, bucket.high, bucket.unit, bucket.label) == (
        low,
        high,
        unit,
        label,
    )


def test_bucket_parse_failure_and_contains() -> None:
    assert Bucket.parse("rainy", market()) is None
    b = Bucket(None, 73, "F", market())
    assert b.contains(73) and not b.contains(74)
    assert Bucket(92, None, "F", market()).contains(100)


def test_event_parse_real_fixture() -> None:
    raw = fixture("weather_event.json")
    event = WeatherEvent.parse(raw, markets_from_event(raw))
    assert event is not None
    assert event.city == "Dallas" and event.icao == "KDAL" and event.unit == "F"
    assert event.day == date(2026, 10, 28) and len(event.buckets) == 11


def test_event_parse_from_factory_and_winner() -> None:
    event = parsed()
    assert event.event_id == "9001" and [b.label for b in event.buckets][:2] == [
        "<=73°F",
        "74-75°F",
    ]
    for fahrenheit in (74.4, 73.5):
        winner = event.winner(to_celsius(fahrenheit, "F"))
        assert winner is not None and winner.label == "74-75°F"
    c_event = parsed(unit="C", titles=["14°C or below", "15°C"])
    assert c_event.winner(30) is None


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"title": "Will it rain?"}, "title"),
        ({"title": "Highest temperature in X on Smarch 3?"}, "month"),
        ({"title": "Highest temperature in X on February 30?"}, "day"),
    ],
)
def test_event_parse_rejects_bad_titles(change: dict, reason: str) -> None:
    raw = weather_event()
    raw.update(change)
    assert WeatherEvent.parse(raw, markets_from_event(raw)) is None


def test_event_parse_rejects_other_sources_and_shapes() -> None:
    raw = weather_event()
    markets = markets_from_event(raw)
    assert WeatherEvent.parse(raw, []) is None
    no_icao = [
        Market(**{**m.__dict__, "description": "Hong Kong Observatory"})
        for m in markets
    ]
    assert WeatherEvent.parse(raw, no_icao) is None


def test_legacy_noaa_rules_are_accepted_for_research_only() -> None:
    raw = weather_event()
    noaa = "highest reading at https://www.weather.gov/wrh/timeseries?site=kdal"
    markets = [
        Market(**{**m.__dict__, "description": noaa}) for m in markets_from_event(raw)
    ]
    assert WeatherEvent.parse(raw, markets) is None
    legacy = WeatherEvent.parse(raw, markets, legacy=True)
    assert legacy is not None and legacy.icao == "KDAL"


@pytest.mark.regression("TP-2")
def test_event_settled_by_a_non_metar_source_is_skipped() -> None:
    raw = weather_event()
    markets = [
        Market(
            **{
                **m.__dict__,
                "description": "the Dallas Airport (KDAL) observatory page",
            }
        )
        for m in markets_from_event(raw)
    ]
    assert WeatherEvent.parse(raw, markets) is None


def test_event_parse_mixed_units_or_no_buckets() -> None:
    raw = weather_event(titles=["70°F or below", "21°C"])
    assert WeatherEvent.parse(raw, markets_from_event(raw)) is None
    raw = weather_event(titles=["cold", "warm"])
    assert WeatherEvent.parse(raw, markets_from_event(raw)) is None


def test_event_year_follows_the_market_end_across_new_year() -> None:
    jan = 1798761600.0  # 2027-01-01T00:00Z
    raw = weather_event(day="December 31", end=jan)
    event = WeatherEvent.parse(raw, markets_from_event(raw))
    assert event is not None and event.day == date(2026, 12, 31)
    dec = 1798675200.0  # 2026-12-31T00:00Z
    raw = weather_event(day="January 1", end=dec)
    event = WeatherEvent.parse(raw, markets_from_event(raw))
    assert event is not None and event.day == date(2027, 1, 1)


def test_distribution_probabilities() -> None:
    event = parsed()
    dist = TempDistribution(mu=to_celsius(75, "F"), sigma=1.0)
    total = sum(dist.bucket_probability(b) for b in event.buckets)
    assert total == pytest.approx(1.0)
    floored = TempDistribution(mu=10.0, sigma=1.0, floor=to_celsius(76.2, "F"))
    assert floored.bucket_probability(event.buckets[1]) == 0.0
    assert floored.bucket_probability(event.buckets[2]) == pytest.approx(1.0)
    point = TempDistribution(mu=20.0, sigma=0.0)
    assert point.cdf(20.0) == 0.0 and point.cdf(20.1) == 1.0


def test_lead_sigma_curve_and_measured_rescaling() -> None:
    lane = WeatherLane(sigma_min=0.6, sigma_per_day=1.0, min_remaining_sigma=0.3)
    assert lead_sigma(lane, 0) == pytest.approx(0.6)
    assert lead_sigma(lane, 24, spread=0.0) == pytest.approx(1.6)
    assert lead_sigma(lane, 24, spread=1.2) == pytest.approx(2.0)
    assert lead_sigma(lane, 30, measured_sd=1.5, spread=9) == pytest.approx(1.5)
    assert lead_sigma(lane, -5, measured_sd=0.1) == 0.3


def test_station_and_bias_loading(tmp_path) -> None:  # noqa: ANN001
    shipped = load_stations()
    assert "KDAL" in shipped and {"lat", "lon"} <= set(shipped["KDAL"])
    path = tmp_path / "s.json"
    path.write_text('{"X": {"lat": 1, "lon": 2}}')
    assert load_stations(path) == {"X": {"lat": 1, "lon": 2}}
    bias = tmp_path / "b.json"
    bias.write_text('{"stations": {"KDAL": {"bias": 1.5, "sd": 1.0, "n": 12}}}')
    assert load_bias(str(bias))["KDAL"]["bias"] == 1.5
    assert load_bias("") == {} and load_bias(str(tmp_path / "none")) == {}


def test_station_zone_falls_back_to_the_offset() -> None:
    assert str(station_zone(Forecast("America/Chicago", 0, {}))) == "America/Chicago"
    fixed = station_zone(Forecast("Not/AZone", 3600, {}))
    assert fixed == timezone(timedelta(seconds=3600))


# -- model -----------------------------------------------------------------
async def test_model_same_day_uses_remaining_hours_and_observed_floor() -> None:
    m = model()
    dist = await m.distribution(parsed())
    assert dist is not None
    assert dist.floor == pytest.approx(19.4)
    assert dist.metrics["lead_days"] == 0 and dist.metrics["models"] == 2
    assert dist.mu == pytest.approx(24.5)
    assert dist.metrics["lead_hours"] == pytest.approx(8.0)
    assert dist.sigma == pytest.approx((((0.6 + 8 / 24) ** 2) + 0.25) ** 0.5)


async def test_model_caches_forecasts_and_metars() -> None:
    transport = weather_routes()
    clock = Clock(NOW)
    m = model(transport, clock=clock)
    await m.distribution(parsed())
    await m.distribution(parsed())
    assert transport.count("/v1/forecast") == 1
    assert transport.count("/api/data/metar") == 1
    clock.advance(LANE.metar_ttl_seconds + 1)
    await m.distribution(parsed())
    assert transport.count("/api/data/metar") == 2
    assert transport.count("/v1/forecast") == 1


async def test_model_next_day_uses_daily_maxima() -> None:
    payload = forecast_payload(day="2026-10-29")
    m = model(weather_routes(**{"/v1/forecast": payload}))
    dist = await m.distribution(parsed(day="October 29"))
    assert dist is not None and dist.metrics["lead_days"] == 1
    assert dist.floor is None and dist.mu == pytest.approx(24.5)


async def test_model_without_forecast_or_station() -> None:
    m = model(weather_routes(**{"/v1/forecast": forecast_payload(day="2026-10-30")}))
    assert await m.distribution(parsed(day="October 29")) is None
    m = model(stations={}, transport=weather_routes(**{"stationinfo": []}))
    assert await m.distribution(parsed()) is None


async def test_model_learns_unknown_stations_from_awc() -> None:
    transport = weather_routes(
        **{"stationinfo": [{"icaoId": "KDAL", "lat": 32.8, "lon": -96.8, "site": "D"}]}
    )
    m = model(transport, stations={})
    assert await m.distribution(parsed()) is not None
    assert m.stations["KDAL"]["name"] == "D"
    await m.station("KDAL")
    assert transport.count("stationinfo") == 1


async def test_model_after_the_local_day_collapses_on_the_observed_max() -> None:
    later = Clock(NOW + 24 * 3600)  # 07:00 local on the 29th
    m = model(clock=later)
    dist = await m.distribution(parsed())
    assert dist is not None and dist.metrics["lead_days"] == -1
    assert dist.mu == pytest.approx(19.4) and dist.sigma == LANE.min_remaining_sigma
    no_obs = model(weather_routes(**{"/api/data/metar": []}), clock=later)
    assert await no_obs.distribution(parsed()) is None


async def test_model_late_in_the_day_without_hours_left() -> None:
    late = Clock(NOW + 16.5 * 3600)  # 23:30 local
    rows = [metar_row(NOW + 8 * 3600)]  # 15:00 local, 19.4
    m = model(weather_routes(**{"/api/data/metar": rows}), clock=late)
    dist = await m.distribution(parsed())
    assert dist is not None and dist.metrics["hours_left"] == 0
    assert dist.floor == pytest.approx(19.4)
    nothing = model(weather_routes(**{"/api/data/metar": []}), clock=late)
    assert await nothing.distribution(parsed()) is None


async def test_model_applies_station_bias_and_measured_sd() -> None:
    m = model(bias={"KDAL": {"bias": 1.0, "sd": 0.5, "n": 12}})
    dist = await m.distribution(parsed())
    assert dist is not None and dist.mu == pytest.approx(25.5)
    assert dist.metrics["bias_c"] == 1.0
    assert dist.sigma == LANE.min_remaining_sigma  # 0.5 x 0.93 / 1.85 < 0.3
    thin = model(bias={"KDAL": {"bias": 1.0, "sd": 0.5, "n": 3}})
    thin_dist = await thin.distribution(parsed())
    assert thin_dist is not None and thin_dist.sigma > dist.sigma


async def test_model_ignores_speci_and_other_days() -> None:
    rows = [
        metar_row(
            NOW - 3600, raw="METAR KDAL 281100Z 30/14 RMK T03000144", kind="SPECI"
        ),
        metar_row(NOW - 13 * 3600, raw="METAR KDAL 272300Z 31/14 RMK T03100144"),
        metar_row(NOW - 1800, raw="METAR KDAL 281130Z RMK NOTHING"),
    ]
    m = model(weather_routes(**{"/api/data/metar": rows}))
    dist = await m.distribution(parsed())
    assert dist is not None and dist.floor is None


# -- scout and analyst -----------------------------------------------------
def scout_for(
    events: list[dict], transport: FakeTransport | None = None, **lane: Any
) -> tuple[WeatherScout, MarketCatalogue]:
    routes = transport or weather_routes()
    routes.add("/events/keyset", {"events": events})
    http = fake_http(routes, max_retries=0)
    gamma = GammaClient(http)
    cat = MarketCatalogue(gamma)
    settings = WeatherLane(**{"models": LANE.models, **lane})
    m = WeatherModel(
        WeatherClient(http), settings, stations=STATIONS, bias={}, clock=Clock(NOW)
    )
    return WeatherScout(gamma, cat, m, settings), cat


async def test_scout_finds_mispriced_buckets() -> None:
    # The model centres on 24.5°C = 76.1°F: 76-77°F is likely, cheap at 0.10.
    scout, cat = scout_for([weather_event()], max_edge=0.6)
    found = await scout.discover()
    assert scout.last_events == 1 and len(cat) == 4
    names = [str(c.name) for c in found]
    assert any("76-77°F Yes" in n for n in names)
    best = found[0]
    assert best.data["lane"] == "weather" and best.data["icao"] == "KDAL"
    assert 0 < best.data[KEY_FAIR] < 1 and "model_p" in best.data


@pytest.mark.regression("TP-1")
async def test_scout_treats_implausible_gaps_as_model_error() -> None:
    scout, _ = scout_for([weather_event()], max_edge=0.07, min_edge=0.06)
    found = await scout.discover()
    assert scout.disagreements > 0
    for candidate in found:
        raw_gap = candidate.data["model_p"] - candidate.data["gamma_ask"]
        assert raw_gap <= 0.07 + 1e-9


async def test_scout_filters_cities_bands_and_states() -> None:
    scout, _ = scout_for([weather_event()], cities=["London"])
    assert await scout.discover() == []
    scout, _ = scout_for([weather_event()], min_price=0.5)
    assert all(c.data["gamma_ask"] >= 0.5 for c in await scout.discover())
    closed = weather_event()
    for raw in closed["markets"]:
        raw["closed"] = True
    scout, _ = scout_for([closed])
    assert await scout.discover() == []
    scout, _ = scout_for([{"title": "Will it rain?", "markets": []}])
    assert await scout.discover() == []


async def test_scout_trades_only_late_in_the_local_day_when_asked() -> None:
    # NOW is 07:00 in Dallas.
    scout, _ = scout_for([weather_event()], min_local_hour=14)
    assert await scout.discover() == []
    scout, _ = scout_for([weather_event()], min_local_hour=6)
    assert await scout.discover() != []
    scout, _ = scout_for([weather_event(day="October 29")], min_local_hour=6)
    assert await scout.discover() == []
    assert scout._in_window({"lead_days": -1, "local_hour": 1})
    assert not scout._in_window({"lead_days": 5, "local_hour": 1})


async def test_scout_skips_far_events_and_survives_station_errors() -> None:
    scout, _ = scout_for([weather_event(day="November 5")])
    assert await scout.discover() == []
    broken = weather_routes(**{"/v1/forecast": OSError("down")})
    scout, _ = scout_for([weather_event()], transport=broken)
    assert await scout.discover() == []
    assert scout.errors and "KDAL" in scout.errors[0]
    scout, _ = scout_for([weather_event(day="October 29")], lead_days=0)
    assert await scout.discover() == []


@pytest.mark.regression("TP-6")
async def test_analyst_rechecks_band_and_guard_on_the_live_book() -> None:
    scout, _ = scout_for([weather_event()], max_edge=0.6)
    candidate = (await scout.discover())[0]

    def analyst(asks: list[tuple[float, float]], **lane: Any) -> WeatherAnalyst:
        books = BookCache(
            ClobClient(fake_http(FakeTransport({"/book": book_payload(asks=asks)})))
        )
        settings = WeatherLane(**{"models": LANE.models, "max_edge": 0.6, **lane})
        return WeatherAnalyst(books, settings, bankroll=1000)

    # Gamma said ~0.10; the live book's 0.005 is below the lane's band.
    assert await analyst([(0.005, 500)]).evaluate(candidate, {}) is None
    # On the live book the gap to the model exceeds max_edge: model error.
    gap_lane = analyst([(0.05, 500)], max_edge=0.1)
    assert await gap_lane.evaluate(candidate, {}) is None
    # One-sided book: no mid, the model alone (still guarded) is the fair value.
    one_sided = FakeTransport({"/book": book_payload(bids=[], asks=[(0.10, 500)])})
    settings = WeatherLane(models=LANE.models, max_edge=0.6)
    lone = WeatherAnalyst(
        BookCache(ClobClient(fake_http(one_sided))), settings, bankroll=1000
    )
    signal = await lone.evaluate(candidate, {})
    assert signal is not None and signal.metrics["book_mid"] is None


@pytest.mark.regression("TP-7")
def test_daily_max_bias_is_not_added_after_the_peak() -> None:
    assert applied_bias(1.5, first_hour=12, peak_hour=15) == 1.5
    assert applied_bias(1.5, first_hour=16, peak_hour=15) == 1.5
    assert applied_bias(1.5, first_hour=17, peak_hour=15) == 0.0


async def test_analyst_prices_on_the_live_book() -> None:
    scout, _ = scout_for([weather_event()])
    candidate = (await scout.discover())[0]
    transport = FakeTransport({"/book": book_payload(asks=[(0.10, 500)])})
    books = BookCache(ClobClient(fake_http(transport)))
    analyst = WeatherAnalyst(books, scout.lane, bankroll=1000)
    signal = await analyst.evaluate(candidate, {})
    assert signal is not None and signal.strategy == "weather"
    assert signal.limit_price == 0.10 and signal.edge is not None and signal.edge > 0
    assert KEY_MARKET not in signal.metrics and signal.metrics[KEY_FAIR] > 0
    assert signal.metrics["book_mid"] is not None
    dear = FakeTransport({"/book": book_payload(asks=[(0.97, 500)])})
    analyst = WeatherAnalyst(
        BookCache(ClobClient(fake_http(dear))), scout.lane, bankroll=1000
    )
    assert await analyst.evaluate(candidate, {}) is None
