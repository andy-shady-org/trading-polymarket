"""``PolymarketModule``: Polymarket plugged into trading-core.

Registered as the ``polymarket`` entry point, so a trading-core config with
``"module": "polymarket"`` runs it (docs/USER-GUIDE.md)::

    trading-core run --config configs/paper.example.json

Instruments are **outcome token ids**. Prices are USDC per share (0..1, shown
in cents); a share pays 1 USDC if its outcome wins. The module:

* quotes from the live CLOB book (best bid/ask, last trade);
* fills paper orders by walking that book, charging the market's taker fee
  (:mod:`trading_polymarket.execution`);
* exits a position the moment its market resolves, redeeming at 1 or 0;
* values open positions at what selling into the bids would return, net of
  the fee (so equity and the circuit breaker see a real exit value);
* refuses live orders until the live gate is passed (docs/GO-NO-GO.md).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from trading_core.module.base import (
    ExecutionRefused,
    Fill,
    MarketQuote,
    OrderRequest,
    TradingModule,
)
from trading_core.money import QuoteAsset
from trading_core.positions import Position
from trading_core.strategy.exits import ExitDecision
from trading_core.strategy.pipeline import Analyst, Scout, StrategyPipeline

from trading_polymarket import __version__
from trading_polymarket.calibration import CalibrationTable, load_or_identity
from trading_polymarket.catalogue import BookCache, MarketCatalogue
from trading_polymarket.clients.clob import BookUnavailable, ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.http import JsonHttp
from trading_polymarket.clients.news import NewsClient
from trading_polymarket.clients.weather import WeatherClient
from trading_polymarket.config import (
    LANE_FAVOURITE,
    LANE_MOMENTUM,
    LANE_WEATHER,
    PolymarketSettings,
)
from trading_polymarket.execution import (
    REASON_RESOLVED,
    LiveExecutor,
    PaperExecutor,
    walk_fee,
)
from trading_polymarket.strategies.favourite import FavouriteAnalyst, FavouriteScout
from trading_polymarket.strategies.filters import BookFilter, MarketStateFilter
from trading_polymarket.strategies.momentum import MomentumAnalyst, MomentumScout
from trading_polymarket.strategies.router import build_pipeline
from trading_polymarket.strategies.weather import (
    WeatherAnalyst,
    WeatherModel,
    WeatherScout,
)

POLYMARKET_QUOTE = QuoteAsset(
    symbol="USDC", decimals=2, atomic_decimals=6, prefix="$", grouping=True
)
EXIT_BID_TARGET = "bid_target"


class PolymarketModule(TradingModule):
    name = "polymarket"
    version = __version__
    quote = POLYMARKET_QUOTE

    def __init__(
        self,
        *,
        http: JsonHttp | None = None,
        clock: Callable[[], float] = time.time,
        calibration: CalibrationTable | None = None,
        stations: Mapping[str, Mapping[str, Any]] | None = None,
        **settings: Any,
    ) -> None:
        super().__init__()
        self.settings = PolymarketSettings.from_mapping(settings)
        self.clock = clock
        self.http = http or JsonHttp(
            timeout=self.settings.http_timeout,
            max_retries=self.settings.http_retries,
            min_interval=self.settings.http_min_interval,
        )
        self.gamma = GammaClient(
            self.http,
            base_url=self.settings.gamma_url,
            default_fee_rate=self.settings.unknown_fee_rate,
        )
        self.clob = ClobClient(self.http, base_url=self.settings.clob_url)
        self.weather_client = WeatherClient(self.http)
        self.catalogue = MarketCatalogue(
            self.gamma, ttl=self.settings.market_ttl_seconds, clock=clock
        )
        self.books = BookCache(
            self.clob, ttl=self.settings.quote_ttl_seconds, clock=clock
        )
        self.paper_executor = PaperExecutor(
            self.catalogue, self.books, self.settings.paper, clock=clock
        )
        self.live_executor = LiveExecutor()
        self.calibration = calibration or load_or_identity(
            self.settings.favourite.calibration_path
        )
        self._stations = stations
        self._pipeline: StrategyPipeline | None = None
        self._built = False
        self.weather_model: WeatherModel | None = None

    # -- strategy -------------------------------------------------------------
    def _lanes(self) -> dict[str, tuple[Scout, Analyst]]:
        s = self.settings
        bankroll = s.bankroll
        lanes: dict[str, tuple[Scout, Analyst]] = {}
        if s.weather.enabled:
            self.weather_model = WeatherModel(
                self.weather_client,
                s.weather,
                stations=self._stations,
                clock=self.clock,
            )
            lanes[LANE_WEATHER] = (
                WeatherScout(self.gamma, self.catalogue, self.weather_model, s.weather),
                WeatherAnalyst(self.books, s.weather, bankroll=bankroll),
            )
        if s.favourite.enabled:
            lanes[LANE_FAVOURITE] = (
                FavouriteScout(
                    self.gamma,
                    self.catalogue,
                    self.calibration,
                    s.favourite,
                    clock=self.clock,
                ),
                FavouriteAnalyst(
                    self.books,
                    self.calibration,
                    s.favourite,
                    bankroll=bankroll,
                    clock=self.clock,
                ),
            )
        if s.momentum.enabled:
            news = NewsClient(self.http) if s.momentum.news else None
            lanes[LANE_MOMENTUM] = (
                MomentumScout(self.gamma, self.catalogue, s.momentum, clock=self.clock),
                MomentumAnalyst(self.books, s.momentum, news=news, clock=self.clock),
            )
        return lanes

    def pipeline(self) -> StrategyPipeline | None:
        if not self._built:
            self._pipeline = build_pipeline(
                self._lanes(),
                market_filter=MarketStateFilter(self.settings, clock=self.clock),
                book_filter=BookFilter(self.settings, self.books),
                max_candidates=self.settings.max_candidates,
            )
            self._built = True
        return self._pipeline

    # -- market data ----------------------------------------------------------
    def _payout_quote(self, token_id: str, payout: float) -> MarketQuote:
        return MarketQuote(
            token_id, bid=payout, ask=payout, last=payout, timestamp=self.clock()
        )

    async def get_quote(self, instrument_id: str) -> MarketQuote:
        market = self.catalogue.cached(instrument_id)
        settled = None if market is None else market.payout(instrument_id)
        if settled is not None:
            return self._payout_quote(instrument_id, settled)
        try:
            book = await self.books.get(instrument_id)
        except BookUnavailable:
            market = await self.catalogue.get(instrument_id, max_age=0.0)
            if market is None:
                raise
            payout = market.payout(instrument_id)
            if payout is not None:
                return self._payout_quote(instrument_id, payout)
            return MarketQuote(
                instrument_id,
                last=market.last_trade_price,
                timestamp=self.clock(),
                stale=True,
            )
        if market is None:
            await self.catalogue.get(instrument_id)
        if self.host is not None:
            self.host.notify_market_data()
        return MarketQuote(
            instrument_id,
            bid=book.best_bid,
            ask=book.best_ask,
            last=book.last_trade_price,
            timestamp=book.timestamp or self.clock(),
        )

    async def get_balance(self) -> float:
        raise ExecutionRefused(LiveExecutor.MESSAGE)

    async def execute(self, order: OrderRequest, *, paper: bool) -> Fill:
        if not paper:
            return await self.live_executor.execute(order)
        return await self.paper_executor.execute(order)

    # -- exits and valuation --------------------------------------------------
    def should_exit(
        self, position: Position, quote: MarketQuote | None, now: float
    ) -> ExitDecision | None:
        market = self.catalogue.cached(position.instrument_id)
        if market is not None:
            payout = market.payout(position.instrument_id)
            if payout is not None:
                return ExitDecision(
                    REASON_RESOLVED,
                    detail=(
                        f"{market.outcome_of(position.instrument_id)} paid {payout:g}"
                    ),
                )
        target = self.settings.exit_at_bid
        if target > 0 and quote is not None and quote.bid and quote.bid >= target:
            return ExitDecision(EXIT_BID_TARGET, detail=f"bid {quote.bid:.3f}")
        return None

    def exit_value(self, position: Position, quote: MarketQuote | None = None) -> float:
        market = self.catalogue.cached(position.instrument_id)
        if market is not None:
            payout = market.payout(position.instrument_id)
            if payout is not None:
                return float(position.size) * payout
        book = self.books.cached(position.instrument_id)
        if book is None or not book.bids:
            return super().exit_value(position, quote)
        walk = book.walk_sell(position.size)
        fee = walk_fee(walk, market.fee) if market is not None else 0.0
        return max(0.0, walk.notional - fee)

    # -- presentation ---------------------------------------------------------
    def format_price(self, price: float | None) -> str:
        if price is None or price < 0:
            return "-"
        return f"{price * 100:.1f}¢"

    def format_size(self, size: float | None) -> str:
        return f"{float(size or 0.0):,.2f}"

    def instrument_label(self, instrument_id: str, name: str | None = None) -> str:
        if name:
            return name if len(name) <= 32 else f"{name[:31]}…"
        text = str(instrument_id or "-")
        return text if len(text) <= 12 else f"{text[:6]}…{text[-4:]}"

    def status_rows(self) -> Sequence[tuple[str, str]]:
        stats = self.http.stats()
        rows = [
            ("api requests", f"{stats['requests']} ({stats['retries']} retried)"),
            ("api failures", str(stats["failures"])),
            ("markets cached", str(len(self.catalogue))),
        ]
        if stats["last_error"]:
            rows.append(("last api error", str(stats["last_error"])[:60]))
        return rows

    def strategy_rows(self) -> Sequence[tuple[str, str]]:
        s = self.settings
        rows = [("lanes", ", ".join(s.enabled_lanes()) or "none")]
        if s.weather.enabled:
            rows.append(
                (
                    "weather",
                    f"edge≥{s.weather.min_edge:.2f} lead≤{s.weather.lead_days}d "
                    f"max ${s.weather.max_notional:g}",
                )
            )
        if s.favourite.enabled:
            identity = bool(self.calibration.meta.get("identity"))
            rows.append(
                (
                    "favourite",
                    f"{s.favourite.min_price:.2f}-{s.favourite.max_price:.2f} "
                    f"≤{s.favourite.max_hours:g}h "
                    + ("NO CALIBRATION" if identity else "calibrated"),
                )
            )
        if s.momentum.enabled:
            rows.append(("momentum", f"move≥{s.momentum.min_move:.2f} (research)"))
        return rows

    # -- operations -----------------------------------------------------------
    def is_public_identifier(self, segment: str) -> bool:
        text = str(segment)
        if text.isdigit() and len(text) >= 20:  # an outcome token id
            return True
        return len(text) == 66 and text.startswith("0x")  # a condition id

    def provenance(self) -> Mapping[str, Any]:
        return {
            "module_version": __version__,
            "settings": self.settings.to_dict(),
            "fee_model": "taker shares*rate*p*(1-p), per market feeSchedule; "
            f"unknown schedules priced at {self.settings.unknown_fee_rate}",
            "calibration_sha256": self.calibration.sha256(),
            "calibration_identity": bool(self.calibration.meta.get("identity")),
        }


__all__ = ["EXIT_BID_TARGET", "POLYMARKET_QUOTE", "PolymarketModule"]
