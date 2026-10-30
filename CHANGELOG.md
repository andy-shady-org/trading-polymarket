# Changelog

All notable changes. Format: Keep a Changelog; versions: SemVer (see
`docs/GO-NO-GO.md` §6).

## 0.2.1: pilot fixes (2026-10-30)

Requires trading-core 0.2.0 or later (the pilots run on 0.2.2). A
money-path release: the 0.2.0 pilots stopped on day 2 (TP-9, TP-10) and the
weather model and sizing changed (TP-11, TP-12), so both lanes start new
Stage 1 pilots with new pre-registered files
([`docs/dev/releases/0.2.1.md`](docs/dev/releases/0.2.1.md)).

### Changed
- Example configs set the new settings explicitly (`heartbeat_seconds`; the
  weather lane's `max_positions_per_day`, `today_error_weight`,
  `intraday_sigma`), so a pre-registered config does not depend on defaults.
- `configs/verdict/weather.json`: the comment now says 150 positions take
  about seven weeks at 3 a day (the rules and their `rules_sha256` are
  unchanged).
- Pilots run in the foreground, in a terminal or tmux, with no service
  manager; cron only for `metars` (docs/PAPER-TRADING.md).

### Fixed
- **TP-9**: positions in markets that had closed were never redeemed: Gamma's
  token lookup returns open markets only, so tokens it misses are now asked
  again with `closed=true`.
- **TP-10**: a flat run went "market data stale" after
  `health_timeout_seconds` and never entered again. The module now runs a
  heartbeat (new setting `heartbeat_seconds`, default 60): it reads the most
  traded open market and its book and tells the engine market data is
  flowing; three failed reads in a row report `polymarket data` degraded.
- **TP-11**: the weather lane's late-day model priced a further rise at
  20–35 % where ~7 % happens (day 1 of the 0.2.0 pilot: ten of ten lost).
  On the event day, after its first METAR, the remaining hours' forecast now
  moves by half of today's error so far, without the station bias, with
  σ 0.8 °C (new settings `today_error_weight`, `intraday_sigma`, measured on
  the intraday replay; the backtest uses the same model). The bias cut-off
  before the first METAR is `first_hour <= peak_hour` (was one hour late).
- **TP-12**: one day's bets were each Kelly-sized as if independent. New lane
  setting `max_positions_per_day` (weather 3, others off): a lane never holds
  more than that many positions in markets closing on one UTC date.

## 0.2.0: Kalshi reference lanes; day-1 pilot fixes (2026-10-29)

Requires trading-core 0.2.0. A money-path release: the weather lane restarts
Stage 1 ([`docs/GO-NO-GO.md`](docs/GO-NO-GO.md) §3.1).

### Added
- **Kalshi client** (`clients/kalshi.py`), free and keyless, read only:
  events (cursor paging), markets, hourly candlesticks, and the historical
  endpoints for archived events. New setting `kalshi_url`.
- **`fed` lane**: Polymarket's "Fed Decision in <Month>?" buckets matched
  every cycle to Kalshi's `KXFEDDECISION` markets for the same meeting
  (`pairs.match_fed`, Yes and No sides); buys when the Polymarket ask is
  `min_edge` below Kalshi's mid (or bid) after fees, with reference guards
  (spread, 24 h volume, age, `max_edge`), sells on convergence (exit reason
  `converged`) or holds to resolution. Off by default.
- **`crossvenue` lane**: the same pricing for pairs in a reviewed file
  (`crossvenue.pairs_path`); off until pairs are approved.
- Research: `fed-history` (settled meetings on both venues, hourly prices
  and candles), `backtest fed` (hourly replay, convergence or resolution,
  Brier scores of Polymarket vs Kalshi at 168/72/24/6/1 h), `pairs suggest`
  (title-similarity candidates for review), `pairs approve|remove|list`.
- Configs: `paper-fed.example.json` (the fed pilot as its own instance),
  pre-registered `verdict/fed.json` and `verdict/crossvenue.json`; the
  example paper config lists the new lanes (off).
- Docs: STRATEGIES (Kalshi lanes, evidence, the duplicate-event trap),
  DATA-SOURCES (Kalshi endpoints), CONFIGURATION, CLI, RESEARCH §4a and the
  2026-10-29 results, GO-NO-GO (status, sample-limited exception, pairs
  without history), PAPER-TRADING (second instance), AGENTS learnings.

### Fixed
- TP-5 (critical): one-sided books were valued at the market's last trade:
  phantom equity peak, breaker trip on day 1. Tokens now mark at their own
  price and are valued by walking their own bids (0 without bids).
- TP-6: the weather analyst trusted the scout's Gamma ask; it now re-checks
  the band and `max_edge` on the live book.
- TP-7: the daily-max bias was added to the remaining hours after the peak.
- TP-8: the pipeline could buy the complement of a held token.
- The CLI reports an API failure as `error: HTTP …` (exit 2) instead of a
  traceback.

### Changed
- flake8 enforces McCabe `max-complexity = 7`; ten functions were split into
  named steps (paper buy, quotes without a book, arbitrage scan, favourite
  scout, history and weather collectors, weather replay). Behaviour is
  unchanged: the fed replay's audit records are byte-identical before and
  after.

### Release record – 0.2.0 (2026-10-29)
- See [`docs/dev/releases/0.2.0.md`](docs/dev/releases/0.2.0.md).
- Release gate: Ruff, Black, flake8, mypy clean; 425 tests, 100% statement
  and branch coverage on Python 3.11, 3.12, 3.13 and 3.14 against
  trading-core 0.2.0. CI on the tag pending.
- Weather lane: Stage 1 restarts (0.1.0 day 1 void, TP-5..TP-8).
- Fed lane: Stage 0 **INCONCLUSIVE – PROCEED (sample-limited)**: 16
  meetings, 23 trades, +$25.08 (adjusted +$23.15), every verdict check but
  `min_positions` passes; +$17.89 at +1 c spread. Kalshi's Brier score is
  not below Polymarket's. Stage 1 starts on its own instance.
- Crossvenue lane: Stage 0 not started (no approved pairs).

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
- Capital stage: weather lane in Stage 1 (paper) from 2026-10-28; pre-registered
  hashes in `docs/dev/releases/0.1.0-weather-stage1.md`. Other lanes: none.
