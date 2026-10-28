from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from trading_polymarket.config import (
    LANE_FAVOURITE,
    LANE_WEATHER,
    FavouriteLane,
    MomentumLane,
    PaperSettings,
    PolymarketSettings,
    WeatherLane,
)


def test_defaults_enable_only_the_weather_lane() -> None:
    settings = PolymarketSettings.from_mapping(None)
    assert settings.enabled_lanes() == [LANE_WEATHER]
    assert settings.lane(LANE_FAVOURITE).enabled is False
    assert settings.to_dict()["weather"]["min_edge"] == 0.06
    with pytest.raises(KeyError):
        settings.lane("nope")


def test_nested_sections_are_built_and_normalised() -> None:
    settings = PolymarketSettings.from_mapping(
        {
            "bankroll": 500,
            "weather": {"cities": ["Dallas"], "models": ["gfs_seamless"]},
            "favourite": {"enabled": True, "exclude_tags": ["sports"]},
            "momentum": {"enabled": True},
            "paper": {"max_slippage": 0.01},
        }
    )
    assert settings.bankroll == 500
    assert settings.weather.cities == ("dallas",)
    assert settings.weather.models == ("gfs_seamless",)
    assert settings.favourite.exclude_tags == ("sports",)
    assert settings.paper.max_slippage == 0.01
    assert settings.enabled_lanes() == ["weather", "favourite", "momentum"]


@pytest.mark.parametrize(
    "data",
    [
        {"typo": 1},
        {"weather": {"typo": 1}},
        {"weather": "not an object"},
        {"bankroll": 0},
        {"max_candidates": 0},
        {"unknown_fee_rate": -1},
        {"exit_at_bid": 1.0},
    ],
)
def test_invalid_settings_are_rejected(data: dict) -> None:
    with pytest.raises(ValueError):
        PolymarketSettings.from_mapping(data)


@pytest.mark.parametrize(
    ("kind", "kwargs"),
    [
        (WeatherLane, {"max_spread": 0}),
        (WeatherLane, {"kelly_fraction": 0}),
        (WeatherLane, {"min_notional": 30}),
        (WeatherLane, {"max_candidates": 0}),
        (WeatherLane, {"models": ()}),
        (WeatherLane, {"sigma_min": 0}),
        (WeatherLane, {"min_price": 0.9, "max_price": 0.5}),
        (WeatherLane, {"lead_days": -1}),
        (WeatherLane, {"concurrency": 0}),
        (WeatherLane, {"min_local_hour": 24}),
        (WeatherLane, {"market_weight": 1}),
        (WeatherLane, {"max_edge": 0.01}),
        (FavouriteLane, {"min_price": 0.99}),
        (FavouriteLane, {"min_hours": 10, "max_hours": 5}),
        (FavouriteLane, {"min_samples": 0}),
        (MomentumLane, {"min_move": 0}),
        (MomentumLane, {"min_price": 0}),
        (PaperSettings, {"max_slippage": -1}),
        (PaperSettings, {"share_decimals": -1}),
    ],
)
def test_invalid_lane_settings(kind: type, kwargs: dict) -> None:
    with pytest.raises(ValueError):
        kind(**kwargs)


def test_every_setting_is_documented() -> None:
    doc = (
        Path(__file__).resolve().parents[3] / "docs" / "CONFIGURATION.md"
    ).read_text()
    for kind in (
        PolymarketSettings,
        PaperSettings,
        WeatherLane,
        FavouriteLane,
        MomentumLane,
    ):
        for item in fields(kind):
            assert f"`{item.name}`" in doc, f"{kind.__name__}.{item.name} undocumented"
