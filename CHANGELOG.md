# Changelog

All notable changes. Format: Keep a Changelog; versions: SemVer (see
`docs/GO-NO-GO.md` §6).

## 0.1.0: first module release (2026-10-28)

### Added
- `PolymarketModule` (entry point `polymarket`) implementing trading-core's
  `TradingModule`: CLOB quotes, payout quotes for resolved markets, stale
  quotes while a closed market awaits resolution, cents/shares formatting,
  public-identifier rules, provenance with the calibration hash.
- Paper execution on the live book: limit-bounded walks, shares rounded down,
  minimum order size and notional, per-level taker fees from each market's
  `feeSchedule` (unknown schedules at the highest rate), partial sells,
  redemption at 1 or 0 with no fee. Live execution refuses every order.
- Free clients with one paced, retrying HTTP layer: Gamma (keyset listings,
  token lookups, search), CLOB (books, windowed price history), Open-Meteo
  (forecast, ensemble, previous runs), Aviation Weather Center (METARs,
  stations), Google News RSS.
- Lanes: **weather** (METAR settlement model with max-so-far floor, station
  bias, multi-model spread, market blending, `max_edge` guard), **favourite**
  (calibrated favourite–longshot bias), **momentum** (research). Shared
  market-state and order-book filters; lane router; fractional-Kelly buy plans
  that keep the minimum edge on every level.
- Research: resolved-market and weather-event collectors, calibration with a
  train/test split, favourite and weather backtests writing trading-core audit
  records, station bias tables, dry-run recorder, record-only arbitrage scanner.
- Intraday weather backtest (`--intraday`: METAR maximum so far + day-ahead
  forecast of the remaining hours), Brier scores of model / market / blend in
  every weather replay, a METAR archive (`metars`) to grow the intraday
  window beyond AWC's 15 days, and `weather.min_local_hour` to restrict the
  lane to the late-day window.
- `trading-polymarket` CLI: scan, weather, record, arb, bias, metars, history,
  weather-history, calibrate, backtest.
- Configs: `paper.example.json`, `live.example.json`, pre-registered
  `verdict/{weather,favourite,momentum}.json`.
- Docs: user guide, strategies, GO/No-Go gates, paper-trading runbook,
  research and results log, configuration, CLI, data sources, architecture,
  live-trading plan; dev testing, bugs, TODO.
- Tests: 300+ (unit mirrored, integration through trading-core's engine,
  Hypothesis properties), 100% statement and branch coverage on 3.11–3.14;
  CI checks out the private trading-core (`TRADING_CORE_TOKEN` secret).

### Fixed
- TP-1: implausible weather edges were trusted (now `max_edge`, market blend, bias).
- TP-2: non-METAR temperature events were priced with the METAR model.
- TP-3: a forced market refresh (`max_age=0`) could serve the cache.
- TP-4: weather events were stored with empty price series and never re-fetched.

### Release record – 0.1.0 (2026-10-28)
- Release gate: code quality, tests and coverage PASS locally on 3.11, 3.12,
  3.13 and 3.14; CI matrix pending the `TRADING_CORE_TOKEN` secret; kill-and-restart
  drill pending the first paper run.
- Favourite lane: Stage 0 **NO-GO** (4,454 resolved markets; calibration
  before 2026-09-15, test after): defaults 5 trades −$22; widest band 746
  trades −$147. Lane stays off. See `docs/RESEARCH.md` §6.
- Weather lane: Stage 0 **INCONCLUSIVE – PROCEED** under the data-limited
  exception: day-ahead NO-GO (3,124 events Aug–Oct: 2,458 trades, −$4,604;
  market Brier 0.057 vs model 0.067); intraday,
  the late-day blend beats the market's Brier score in both halves of 12–27
  October but the held-out PnL is not positive. Paper pilot allowed for the
  late-day window only (`lead_days: 0`, `min_local_hour: 15`).
- Capital stage: none (paper not started).
