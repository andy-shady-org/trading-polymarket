"""Module settings: the ``module_settings`` object of a trading-core config.

Everything has a safe default, so ``"module_settings": {}`` runs. Unknown keys
are rejected (a typo must not silently fall back to a default). Amounts are in
USDC. docs/CONFIGURATION.md documents every key.

Lanes are the module's independent strategies. Each lane tags its trades with
its own ``strategy`` so ``trading-core-audit verdict --strategy <lane>`` judges
it on its own (docs/GO-NO-GO.md):

* ``weather``   - daily-temperature markets priced against free forecasts and
  live METAR observations (the lane with a modelled, testable edge);
* ``favourite`` - favourite-longshot bias near resolution, sized from a
  calibration table built from real resolved markets;
* ``momentum``  - research lane: follows sharp moves on busy markets and
  records attention metrics; off by default, no claimed edge;
* ``fed``        - Fed-decision buckets priced from Kalshi's quotes for the
  same meeting (``KXFEDDECISION``);
* ``crossvenue`` - any question listed on both Polymarket and Kalshi, from a
  reviewed pairs file (``trading-polymarket pairs``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from typing import Any, TypeVar

from trading_polymarket.clients.clob import CLOB_URL
from trading_polymarket.clients.gamma import GAMMA_URL
from trading_polymarket.clients.kalshi import KALSHI_URL
from trading_polymarket.clients.weather import DEFAULT_MODELS

T = TypeVar("T")

LANE_WEATHER = "weather"
LANE_FAVOURITE = "favourite"
LANE_MOMENTUM = "momentum"
LANE_FED = "fed"
LANE_CROSSVENUE = "crossvenue"
LANES = (LANE_WEATHER, LANE_FAVOURITE, LANE_MOMENTUM, LANE_FED, LANE_CROSSVENUE)
REFERENCE_MID = "mid"
REFERENCE_BID = "bid"


def _build(cls: type[T], data: Mapping[str, Any] | None, where: str) -> T:
    data = dict(data or {})
    known = {f.name for f in fields(cls)}  # type: ignore[arg-type]
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(f"unknown {where} keys: {', '.join(unknown)}")
    return cls(**data)


@dataclass(frozen=True)
class LaneLimits:
    """Market-quality screens shared by every lane (each lane sets its own)."""

    enabled: bool = False
    min_volume_24h: float = 0.0
    min_liquidity: float = 0.0
    max_spread: float = 0.10
    min_ask_depth: float = 5.0  # USDC within ``depth_window`` of the best ask
    depth_window: float = 0.03
    min_edge: float = 0.03  # probability points after fees
    kelly_fraction: float = 0.25
    min_notional: float = 2.0
    max_notional: float = 25.0
    max_candidates: int = 40
    # Open positions the lane may hold in markets closing on one UTC date
    # (0: no cap). Bets on one day share its weather, one meeting, one
    # thesis: Kelly-sizing each as independent over-bets the thesis (TP-12).
    max_positions_per_day: int = 0

    def _check(self) -> None:
        if self.max_spread <= 0 or self.depth_window < 0:
            raise ValueError("max_spread must be > 0 and depth_window >= 0")
        if not 0 < self.kelly_fraction <= 1:
            raise ValueError("kelly_fraction must be within (0, 1]")
        if not 0 < self.min_notional <= self.max_notional:
            raise ValueError("need 0 < min_notional <= max_notional")
        if self.min_edge < 0 or self.max_candidates < 1:
            raise ValueError("min_edge must be >= 0 and max_candidates >= 1")
        if self.max_positions_per_day < 0:
            raise ValueError("max_positions_per_day must be >= 0 (0: no cap)")


@dataclass(frozen=True)
class WeatherLane(LaneLimits):
    enabled: bool = True
    max_spread: float = 0.15
    min_ask_depth: float = 2.0
    min_edge: float = 0.06
    max_notional: float = 15.0
    max_positions_per_day: int = 3
    min_price: float = 0.02
    max_price: float = 0.97
    lead_days: int = 1  # trade today's and tomorrow's events (local dates)
    models: tuple[str, ...] = DEFAULT_MODELS
    # Uncertainty curve: sigma_min + sigma_per_day x hours-to-peak / 24 (°C).
    # A station's measured day-ahead sd rescales it (strategies/weather.py).
    sigma_min: float = 0.6
    sigma_per_day: float = 1.0
    # Fair value = (1 - w) x model + w x market mid: the market knows things
    # the model does not (station quirks, local forecasters).
    market_weight: float = 0.5
    # A raw model-vs-ask gap above this is treated as a model error, not edge.
    max_edge: float = 0.25
    min_remaining_sigma: float = 0.3
    # On the event day, after its first METAR (TP-11): the remaining hours'
    # forecast moves by this share of today's error so far, and its maximum
    # has this uncertainty (°C). Measured on the intraday replay.
    today_error_weight: float = 0.5
    intraday_sigma: float = 0.8
    peak_hour: int = 15  # local hour by which the daily max is usually set
    # Trade an event only on its own local day from this hour on (0: off).
    # Late in the day the observed maximum decides most buckets.
    min_local_hour: int = 0
    forecast_ttl_seconds: float = 1800.0
    metar_ttl_seconds: float = 300.0
    cities: tuple[str, ...] = ()  # allow-list of city names; empty: all
    bias_path: str = ""  # per-station bias table (trading-polymarket bias)
    max_events: int = 200
    concurrency: int = 8  # stations priced in parallel

    def __post_init__(self) -> None:
        object.__setattr__(self, "models", tuple(self.models))
        object.__setattr__(self, "cities", tuple(c.lower() for c in self.cities))
        self._check()
        self._check_model()
        if not 0 <= self.min_price < self.max_price <= 1:
            raise ValueError("weather needs 0 <= min_price < max_price <= 1")
        if not 0 <= self.market_weight < 1 or self.max_edge <= self.min_edge:
            raise ValueError(
                "weather needs 0 <= market_weight < 1, max_edge > min_edge"
            )
        if not 0 <= self.min_local_hour <= 23:
            raise ValueError("weather.min_local_hour must be within 0..23")
        if self.lead_days < 0 or self.concurrency < 1:
            raise ValueError("weather.lead_days >= 0 and concurrency >= 1")

    def _check_model(self) -> None:
        if not self.models:
            raise ValueError("weather.models must not be empty")
        if self.sigma_min <= 0 or self.sigma_per_day < 0:
            raise ValueError("weather sigma settings must be positive")
        if not 0 <= self.today_error_weight <= 1 or self.intraday_sigma <= 0:
            raise ValueError(
                "weather needs 0 <= today_error_weight <= 1, intraday_sigma > 0"
            )


@dataclass(frozen=True)
class FavouriteLane(LaneLimits):
    min_volume_24h: float = 5000.0
    min_liquidity: float = 2000.0
    max_spread: float = 0.03
    min_ask_depth: float = 50.0
    min_edge: float = 0.01
    min_price: float = 0.80
    max_price: float = 0.97
    min_hours: float = 1.0
    max_hours: float = 72.0
    min_samples: int = 200  # calibration cell size before any trade
    calibration_path: str = ""
    max_pages: int = 3
    exclude_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "exclude_tags", tuple(self.exclude_tags))
        self._check()
        if not 0 < self.min_price < self.max_price < 1:
            raise ValueError("favourite needs 0 < min_price < max_price < 1")
        if not 0 <= self.min_hours < self.max_hours:
            raise ValueError("favourite needs 0 <= min_hours < max_hours")
        if self.min_samples < 1:
            raise ValueError("favourite.min_samples must be at least 1")


@dataclass(frozen=True)
class MomentumLane(LaneLimits):
    min_volume_24h: float = 20000.0
    min_liquidity: float = 5000.0
    max_spread: float = 0.03
    min_ask_depth: float = 100.0
    min_edge: float = 0.0
    min_notional: float = 2.0
    max_notional: float = 5.0
    min_move: float = 0.08  # one-hour price change that counts as a move
    min_price: float = 0.15
    max_price: float = 0.85
    min_hours: float = 24.0
    news: bool = False  # add Google News attention as a metric
    max_pages: int = 2

    def __post_init__(self) -> None:
        self._check()
        if self.min_move <= 0:
            raise ValueError("momentum.min_move must be positive")
        if not 0 < self.min_price < self.max_price < 1:
            raise ValueError("momentum needs 0 < min_price < max_price < 1")


@dataclass(frozen=True)
class ReferenceLane(LaneLimits):
    """A lane priced from Kalshi's quote for the same question.

    ``reference`` is ``"mid"`` (Kalshi's mid is the fair value) or ``"bid"``
    (the conservative choice: buy on Polymarket only below what Kalshi's
    buyers already pay). A Kalshi quote wider than ``max_reference_spread``
    or thinner than ``min_reference_volume`` (24 h contracts) is no reference.
    """

    min_volume_24h: float = 1000.0
    min_liquidity: float = 1000.0
    max_spread: float = 0.04
    min_ask_depth: float = 20.0
    min_edge: float = 0.02
    max_edge: float = 0.15  # a bigger gap suggests different rules, not money
    min_price: float = 0.03
    max_price: float = 0.97
    reference: str = REFERENCE_MID
    max_reference_spread: float = 0.04
    min_reference_volume: float = 500.0
    reference_ttl_seconds: float = 60.0
    max_reference_age_seconds: float = 600.0
    min_hours: float = 1.0
    exit_on_convergence: bool = True
    convergence_margin: float = 0.0

    def __post_init__(self) -> None:
        self._check()
        if self.reference not in (REFERENCE_MID, REFERENCE_BID):
            raise ValueError("reference must be 'mid' or 'bid'")
        if not 0 < self.min_price < self.max_price < 1:
            raise ValueError("reference lanes need 0 < min_price < max_price < 1")
        if self.max_edge <= self.min_edge or self.max_reference_spread <= 0:
            raise ValueError("need max_edge > min_edge and max_reference_spread > 0")
        if self.convergence_margin < 0 or self.min_hours < 0:
            raise ValueError("convergence_margin and min_hours must be >= 0")


@dataclass(frozen=True)
class FedLane(ReferenceLane):
    """Fed decision buckets against Kalshi's KXFEDDECISION markets."""

    min_volume_24h: float = 5000.0
    min_liquidity: float = 5000.0
    search_query: str = "Fed Decision in"  # Gamma public search for the events


@dataclass(frozen=True)
class CrossVenueLane(ReferenceLane):
    """Any question listed on both venues, from a reviewed pairs file."""

    pairs_path: str = "data/pairs.json"


@dataclass(frozen=True)
class PaperSettings:
    """How paper fills are simulated against the live book."""

    max_slippage: float = 0.02  # beyond the best price when no limit is given
    price_cap: float = 0.99
    min_notional: float = 1.0
    share_decimals: int = 2

    def __post_init__(self) -> None:
        if self.max_slippage < 0 or not 0 < self.price_cap <= 1:
            raise ValueError("paper.max_slippage >= 0 and 0 < price_cap <= 1")
        if self.min_notional < 0 or self.share_decimals < 0:
            raise ValueError("paper.min_notional and share_decimals must be >= 0")


@dataclass(frozen=True)
class PolymarketSettings:
    gamma_url: str = GAMMA_URL
    clob_url: str = CLOB_URL
    http_timeout: float = 15.0
    http_retries: int = 3
    http_min_interval: float = 0.05
    quote_ttl_seconds: float = 5.0
    market_ttl_seconds: float = 120.0
    # Seconds between venue reads that keep the engine's market-data health
    # fresh while no position is held (0: off). Below health_timeout_seconds.
    heartbeat_seconds: float = 60.0
    # Rate charged when a fee-enabled market publishes no schedule: the
    # highest category rate, so paper is never cheaper than live.
    unknown_fee_rate: float = 0.07
    bankroll: float = 1000.0  # what lane Kelly sizing is a fraction of
    max_candidates: int = 80
    exit_at_bid: float = 0.0  # sell when the bid reaches this (0: hold)
    paper: PaperSettings = field(default_factory=PaperSettings)
    weather: WeatherLane = field(default_factory=WeatherLane)
    favourite: FavouriteLane = field(default_factory=FavouriteLane)
    momentum: MomentumLane = field(default_factory=MomentumLane)
    fed: FedLane = field(default_factory=FedLane)
    crossvenue: CrossVenueLane = field(default_factory=CrossVenueLane)
    kalshi_url: str = KALSHI_URL

    def __post_init__(self) -> None:
        if self.bankroll <= 0 or self.max_candidates < 1:
            raise ValueError("bankroll must be > 0 and max_candidates >= 1")
        if self.unknown_fee_rate < 0 or not 0 <= self.exit_at_bid < 1:
            raise ValueError("unknown_fee_rate >= 0 and 0 <= exit_at_bid < 1")
        if self.heartbeat_seconds < 0:
            raise ValueError("heartbeat_seconds must be >= 0 (0: off)")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> PolymarketSettings:
        raw = dict(data or {})
        nested = {
            "paper": PaperSettings,
            "weather": WeatherLane,
            "favourite": FavouriteLane,
            "momentum": MomentumLane,
            "fed": FedLane,
            "crossvenue": CrossVenueLane,
        }
        built: dict[str, Any] = {}
        for key, kind in nested.items():
            if key in raw:
                value = raw.pop(key)
                if not isinstance(value, Mapping):
                    raise ValueError(f"module_settings.{key} must be an object")
                built[key] = _build(kind, value, f"module_settings.{key}")
        settings = _build(cls, raw, "module_settings")
        return cls(**{**_shallow(settings), **built})

    def lane(self, name: str) -> LaneLimits:
        if name not in LANES:
            raise KeyError(f"unknown lane {name!r}")
        lane: LaneLimits = getattr(self, name)
        return lane

    def enabled_lanes(self) -> list[str]:
        return [name for name in LANES if self.lane(name).enabled]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _shallow(settings: PolymarketSettings) -> dict[str, Any]:
    return {f.name: getattr(settings, f.name) for f in fields(settings)}


__all__ = [
    "LANES",
    "LANE_CROSSVENUE",
    "LANE_FED",
    "REFERENCE_BID",
    "REFERENCE_MID",
    "CrossVenueLane",
    "FedLane",
    "ReferenceLane",
    "LANE_FAVOURITE",
    "LANE_MOMENTUM",
    "LANE_WEATHER",
    "FavouriteLane",
    "LaneLimits",
    "MomentumLane",
    "PaperSettings",
    "PolymarketSettings",
    "WeatherLane",
]
