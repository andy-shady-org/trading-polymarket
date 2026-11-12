# Changelog

Every release of trading-polymarket, newest first, with its release record.
The format is [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/);
versions follow semantic versioning as set out in
[`docs/dev/RELEASE-GATE.md` §6](docs/dev/RELEASE-GATE.md#6-versioning), with
no pre-releases. Entries written before 2026-10-31 keep their original
headings (`## 0.2.1: pilot fixes (2026-10-30)`) and are not edited.

## [Unreleased]

## [0.6.1] - 2026-11-12

A PATCH release so this module can run on trading-core 0.8.0: no code
changes.

### Changed
- `trading-core>=0.6.0,<0.9` (was `<0.8`): 0.8.0 adds the modules' shared plumbing (FEAT-184) and changes nothing this module uses. Its own HTTP client (`clients/http.py`) stays here for now: it paces per host, posts bodies and counts for the dashboard, which trading-core's `ops.http` does not yet (trading-core `docs/dev/TODO.md`).

### Release record – v0.6.1 (2026-11-12)
- Commit: the head of `release/v0.6.1` (the tag goes on its merge commit on `main`)
- Release gate: PASS on Linux for every item that runs here: `nox -s format` (no changes), `lint` (ruff, black, flake8 with complexity ≤ 7: 0 findings), `mypy` (0 issues), `tests-3.11` to `tests-3.14`, `audit` (no known vulnerability), `package` (a private wheel of 58 files, no tests); still to do: CI on the merge and the signed tag, which the operator makes
- Tests: 628 collected, all passed on 3.11, 3.12, 3.13 and 3.14; coverage 100% of statements and branches on each
- Checked: the suite on trading-core `v0.8.0`'s tree (`feature/feat-184`); no code changed
- Used by: no run moves onto it; `weather-1`, `fed-1`, `arb-1`, `sports-1` and `ticks-2` keep their release copies

## [0.6.0] - 2026-11-07

The full-set scanner (FEAT-102), record-only, for the run `arb-1`: every
open neg-risk event's Yes set and No set priced on full books with fees and
depth, every gap's lifetime, size and profit recorded for a week, and the
pre-registered decision. Fixes TP-13 (partial sets read as gaps). No lane,
setting or fill changes, so no run's result changes; `weather-1` and `fed-1`
stay on `v0.4.0`, `sports-1` on `v0.5.0`. Tested on trading-core `v0.7.0`;
needs trading-core 0.6.0 or later (unchanged). Release record:
[`docs/dev/releases/0.6.0.md`](docs/dev/releases/0.6.0.md).

### Added
- `trading-polymarket arb --loop` and `arb-report` (FEAT-102, `research/arb_loop.py`, `research/arb_report.py`): record-only, every full-set gap on Polymarket, how big and how long. Every open neg-risk event's **Yes set** (pays 1) and **No set** (pays `n − 1`), priced on full books with each market's fee and walked for depth (the cost of 10, 50 and 100 sets; the most sets that each still earn `--min-profit`, 0.5 c, and their profit). Gamma's events every 15 minutes, every set's books every 5 minutes, sets within 3 c of a gap every 30 s and open gaps every 5 s; one folder a UTC day with each gap's lifetime, size, profit and longest run at $5 or more (`gaps.jsonl`), every read of an open gap with each leg's top levels (`observations.jsonl.gz`) and coverage (`sweeps.jsonl`, `catalogue.jsonl`). `arb-report` gives FEAT-102's decision for the run `arb-1` (`docs/dev/runs/arb-1.md`), with the qualifying gaps' days to resolution and return a year (each gap records its set's latest end date, `resolves`). `arb` without `--loop` prints the sets closest to a gap after one pass.
- `ClobClient.books`: many books in one `POST /books` (500 a request); `JsonHttp.post_json` (the transport takes an optional body); `GammaClient.event_pages` (Gamma's events a page at a time).

### Changed
- `arb` no longer checks binary Yes + No pairs (a market's No book is its Yes book mirrored, so a pair costs 1 plus the spread), reads every open event instead of the 5 most active pages, and writes a folder (`--out`, `data/arb`) instead of `data/arb.jsonl`; `--min-size` is gone (a set's minimum is its legs' minimum order size).

### Fixed
- TP-13: `arb` summed the asks of an event's tradable markets as if they were every outcome, so a set missing an outcome that could still win (an inactive or unresolved market, or an augmented event's `Other` before it accepts orders) read as a gap. A set is now built only when it is complete.

## [0.5.0] - 2026-11-07

Research commands, record-only: the sports listing-gap recorder and its
report (FEAT-168, for the run `sports-1`), strategy-library rows from the
collected data (FEAT-149), the liquidity-rewards scan (FEAT-153) and the
expiry-fade backtest (FEAT-103, NO-GO). No lane, setting or fill changes, so
no run's result changes; `weather-1` and `fed-1` stay on `v0.4.0`. Tested on
trading-core `v0.7.0`; needs trading-core 0.6.0 or later. Release record:
[`docs/dev/releases/0.5.0.md`](docs/dev/releases/0.5.0.md).

### Added
- `trading-polymarket sports-gaps` and `sports-gaps-report` (FEAT-168, `research/sports_gaps.py`, `research/sports_gaps_report.py`): record-only, tennis and esports matches on both venues from listing. Every 2 minutes, for each match listed on Polymarket (Gamma's newest moneyline markets, leagues `atp` `wta` `itf` `cs2` `dota2` `val` `lol` `codmw` `mlbb` `ow`) and Kalshi (13 match series), paired by start time and side names (one to one, never guessed): Polymarket's best bid and ask with sizes (the first outcome's book; the second mirrors it) and Kalshi's for each side, until 3 h after the start; each venue's listing time. The report finds gaps (ask plus fee at least 0.02 below Kalshi's mid, Kalshi's spread at most 0.05, $5 at the ask) as events, by hours after listing, settles them from Gamma and gives the pre-registered `sports-1` decision (`docs/dev/runs/sports-1.md`). From the 2026-10-30 study's listing-time lead.
- `trading-polymarket updown-backtest --rule fade` (FEAT-103, `research/updown_fade.py`): the expiry fade, pre-registered before its run: late in a window with spot flat, buy the side 15 c or more from 0.50 (and its mirror, the favourite), next buy print, held to settlement, judged by FEAT-147's bar with a 3 s stress rule. Result on the 30-day BTC 5-minute backfill: NO-GO, −8.0% on stake over 6,139 trades (`docs/dev/RESULTS.md`).
- `trading-polymarket lane-rows` (FEAT-149, `research/lane_rows.py`): data already collected (`history`, `weather-history`, `fed-history`, `updown-history`) as trading-core's strategy-library rows, for `trading-core-lanes sweep`: each outcome token an instrument with a listing (`resolves_at`), a reading per price point (Kalshi's last closed mid as `reference` for the Fed buckets), a trade print per Up/Down taker trade (wallet, price × shares; `--print-offset` for FEAT-147's offset) and an outcome at settlement. `--fee-rate` keeps one taker rate, so each sweep runs at one rate with trading-core's `--price-fee-rate`. Needs trading-core `>=0.6.0` (the library's rows); the requirement's floor rises from 0.5.0.
- `trading-polymarket rewards-scan` (FEAT-153): every market paying liquidity rewards today, its terms, the shares already resting inside its reward spread, and a one-snapshot estimate of a two-sided quote's reward, ranked, with ended markets and wide books flagged (`research/rewards.py`); `ClobClient.rewards_markets`, `GammaClient.raw_markets_by_condition_ids`.

### Changed
- `trading-core>=0.6.0,<0.8` (was `>=0.5.0`): `lane-rows` writes trading-core's strategy-library rows (`trading_core.lanes`, 0.6.0).

## 0.4.0: crypto Up/Down research (2026-11-04)

Research commands for crypto Up/Down markets (FEAT-146, FEAT-147); no
lane, setting or fill changes, so no run's result changes. Tested on
trading-core `v0.7.0`; needs trading-core 0.5.0 or later (its WebSocket
loop). The backtest's result, NO-GO, is in
[`docs/dev/RESULTS.md`](docs/dev/RESULTS.md). Release record:
[`docs/dev/releases/0.4.0.md`](docs/dev/releases/0.4.0.md).

### Added
- `trading-polymarket updown-history` (FEAT-146, first part): collects crypto Up/Down markets of one asset and window, a day at a time, with every trade to the second (Polymarket's data API, `/v2/trades`), each market's outcome and Chainlink start and end prices (Gamma), and one-second spot (Binance's market-data mirror). Days are written whole and the command is resumable. New clients `clients/data_api.py` and `clients/spot.py`; `GammaClient.raw_markets_by_slugs`.
- `trading-polymarket updown-backtest` (FEAT-146, second part): replays the pre-registered late-longshot rule on the collected trades (`research/updown_backtest.py`): the primary rule and the descriptive grid, each judged by the pre-registered bar, and the primary rule's trades as trading-core audit records.
- `trading-polymarket ticks` and `ticks-report` (FEAT-147, part 1; FEAT-101's recorder): record the current and next Up/Down markets' best bid and ask, every fill and Binance spot to the millisecond with round trips to the CLOB, and report our delay against how long stale asks live, the data API's timestamp offset and the pre-registered decision (`research/ticks.py`, `research/ticks_report.py`).
- `updown-backtest --rule stale` (FEAT-147, part 2): the pre-registered stale-quote rule with `--timestamp-offset` (`research/updown_stale.py`); `--out` now defaults to `data/backtest/updown-<rule>.jsonl` (was `updown.jsonl`).
- The data API client keeps each trade's `transaction_hash`.

### Changed
- `trading-core>=0.5.0,<0.8` (was `>=0.3.0`): `ticks` runs on trading-core's WebSocket loop (`trading_core.ops.stream`, 0.5.0).
- `Ctrl-C` ends any command with "stopped" and exit code 130 instead of a traceback.

### Docs
- The runtime folder is `runtimes/polymarket` (it was `runtime-trading` until the repository split of 2026-11-02); `docs/dev/RUNBOOK.md` §9 runs the research commands from a release copy.
- FEAT-146's result in `docs/dev/RESULTS.md`, with two studies on its data (who wins in these markets; cheap buys after a spot move) and FEAT-147 proposed and pre-registered from them; `STRATEGY-LEDGER.md` and `LESSONS.md` copied from trading-core.

## 0.3.0: trading-core 0.7.0 and trusted loading (2026-11-04)

Tested on trading-core `v0.7.0`; no lane, setting or fill changes. Release
record: [`docs/dev/releases/0.3.0.md`](docs/dev/releases/0.3.0.md).

### Changed
- `trading-core>=0.3.0,<0.8` (was `<0.6` on `main`); CI checks out trading-core `v0.7.0` (was `main`).
- `trading-core>=0.3.0,<0.6` (was `>=0.2.0`, with no upper bound): a fresh install could pull a trading-core this module was never tested on, and trusted loading (trading-core 0.3.0) checks the declared range. Tested on trading-core 0.4.0 and 0.5.0. The running `v0.2.1` installs are unaffected.

### Docs
- The intraday weather data's two event counts explained: 519 in the late-day study, 542 in the Stage 0 replay; they use different coverage tests (`RESULTS.md` 2026-10-30, `STRATEGY.md`) (2026-11-03).
- Shared pages `docs/STRATEGY-LEDGER.md` and `docs/LESSONS.md`, copied unchanged from trading-core (its `docs/dev/DOCUMENTATION.md` §2.4), and an `AGENTS.md` section that sends every agent to them before a lane, run or venue is proposed (2026-11-03).
- Release steps (2026-10-31): merge in the GitHub UI, sign and push the tag on the Mac (never in the UI: a tag GitHub creates is unsigned), then optionally publish the GitHub Release on the existing tag; a tag ruleset on `v*` blocks moving or deleting a release tag (`CONTRIBUTING.md`). README badges: code style, signed releases, stars, issues, forks, pull requests, contributors, licence (static: the repository is private). `SECURITY.md` gains "Signed releases".
- Costs: development costs are recorded in trading-core's `docs/dev/COSTS.md`; features that cross repositories carry **Needs** / **Needed by** links (2026-10-31).
- The documentation follows trading-core's `docs/dev/DOCUMENTATION.md`.
  Moved, with a one-line pointer left behind: `docs/GO-NO-GO.md` →
  `docs/dev/RELEASE-GATE.md` (§1 is now the only place status lives; the
  standard's stage names, release-record template and versioning policy),
  `docs/PAPER-TRADING.md` → `docs/dev/RUNBOOK.md` (with the runtime-trading
  folder, smoke run, run records and drills), `docs/RESEARCH.md` §6 →
  `docs/dev/RESULTS.md` (unchanged, newest first, with an index),
  `docs/STRATEGIES.md` → `docs/STRATEGY.md`, and its ideas →
  `docs/dev/PROPOSED-FEATURES.md`. New: `docs/ENVIRONMENT.md`,
  `docs/FEATURES.md`, `docs/dev/README.md`, `docs/dev/DONE.md`,
  `docs/dev/ARCHITECTURE-DECISIONS.md` (ADR-001 to ADR-014),
  `docs/dev/COSTS.md`, `docs/dev/runs/README.md`, `CONTRIBUTING.md`,
  `SECURITY.md`. Stale statements fixed against the code (CLI flags and
  exit codes, the package map, the test count, lanes in the user guide,
  live trading "not built in 0.2.1"). Counted runs from now on are named
  `weather-1`, `fed-1`, …; `weather-0.2.1` and `fed-0.2.1` keep their names.
  No code or config changed.

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
