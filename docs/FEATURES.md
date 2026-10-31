# Features

What trading-polymarket has built, as of v0.2.1, and what each part does for
the operator. "Built" means the code exists and is tested at 100% coverage,
not that a lane makes money: each lane's stage is in
[`dev/RELEASE-GATE.md` §1](dev/RELEASE-GATE.md#1-current-status) and every
result in [`dev/RESULTS.md`](dev/RESULTS.md). Ideas not built are in
[`dev/PROPOSED-FEATURES.md`](dev/PROPOSED-FEATURES.md).

Everything here was built before the shared `FEAT-<n>` series reached this
repository, so it is listed by name, without an ID (trading-core's
`docs/dev/DOCUMENTATION.md` §9). New features take a `FEAT-<n>`.

## 1. The trading-core module (`polymarket`)

`trading_polymarket.module:PolymarketModule` implements trading-core's
`TradingModule` and is registered in the `trading_core.modules` entry-point
group as `polymarket`, so a settings file with `"module": "polymarket"` runs
it (`trading-core run --config configs/paper.example.json`). Since 0.1.0;
how it meets the contract: [`ARCHITECTURE.md` §3](ARCHITECTURE.md#3-the-module-contract-method-by-method).

- **Quotes** from the live CLOB book, in USDC per share and shown in cents
  (`61.5¢`); a resolved market quotes its payout; a closed market awaiting
  resolution quotes **stale**, so the engine holds and fires no price exit.
- **Resolution**: a position whose market resolved is sold at 1 or 0 in the
  next cycle (exit reason `resolved`). Closed markets are looked up with
  `closed=true` too, so they are never missed (TP-9, 0.2.1).
- **Valuation for the breaker**: what selling into the token's own bids
  returns after the fee, 0 when it has no bids (TP-5, 0.2.0).
- **Heartbeat**: every `heartbeat_seconds` (60) the module reads the most
  traded open market and its book and tells the engine market data is
  flowing, held position or not; three failures in a row report
  `polymarket data` degraded (TP-10, 0.2.1).
- **Dashboard rows**: API requests, retries, failures, the last API error,
  markets cached; the enabled lanes with their key thresholds, and
  `NO CALIBRATION` when the favourite lane has no table.
- **Provenance**: the module version, every setting, the fee model and the
  calibration's sha256 go into each run's `run_started` record.
- **Live execution refuses** every order and the balance read
  (`ExecutionRefused`), so the engine keeps entries blocked in live mode
  ([`LIVE-TRADING.md`](LIVE-TRADING.md)).

## 2. Paper fills on the live book

Since 0.1.0 ([`ARCHITECTURE.md` §5](ARCHITECTURE.md#5-fill-model-paper)):
every paper buy reads a fresh book and walks its asks up to the limit;
shares are rounded down to 0.01; the market's `orderMinSize` and
`paper.min_notional` are enforced; each level pays the market's taker fee
from its `feeSchedule` (a fee-enabled market without one pays
`unknown_fee_rate`, 0.07); partial sells are reported; redemption at 1 or 0
is free.

## 3. Lanes

Each lane has its own scout, analyst, settings (`module_settings.<lane>`) and
verdict file; the rules are in [`STRATEGY.md`](STRATEGY.md).

| Lane | Since | What it does | Default |
|---|---|---|---|
| `weather` | 0.1.0 | Prices daily highest-temperature buckets from a multi-model forecast and the live METAR maximum against the published settlement rule; guards `max_edge`, `market_weight`; only METAR-settled events (TP-1, TP-2). 0.2.0: re-checks on the live book (TP-6), no bias after the peak (TP-7). 0.2.1: on the event day the forecast moves by half of today's error (`today_error_weight`, `intraday_sigma`, TP-11); at most `max_positions_per_day` (3) per closing date (TP-12) | on |
| `favourite` | 0.1.0 | Buys favourites near resolution where a calibration table built on resolved markets beats price plus fee | off |
| `momentum` | 0.1.0 | Research: buys a small fixed amount after a sharp one-hour move and records the move, the book and (optionally) Google News headlines | off |
| `fed` | 0.2.0 | Matches Polymarket's "Fed Decision in <Month>?" buckets to Kalshi's `KXFEDDECISION` markets every cycle, buys below Kalshi's quote after fees, sells on convergence (exit reason `converged`) or holds to resolution | off (on in `configs/paper-fed.example.json`) |
| `crossvenue` | 0.2.0 | The same pricing for any Polymarket/Kalshi pair a human approved (`pairs approve`) | off |

## 4. The shared pipeline

Since 0.1.0: one scout per enabled lane, then `MarketStateFilter` (open,
volume, liquidity, per lane), `BookFilter` (spread, depth near the ask) and
`LaneRouter`, which hands each candidate to its lane's analyst. Every signal
carries its lane as `strategy`. Buy plans use fractional Kelly and keep
`min_edge` on every level they buy. The pipeline never offers the complement
of a held token (TP-8, 0.2.0) and drops signals past a lane's
`max_positions_per_day` (0.2.1).

## 5. Arbitrage scanner (record only)

Since 0.1.0: `trading-polymarket arb` checks live books for binary pairs
whose asks plus fees sum below 1 and neg-risk sets whose Yes asks plus fees
sum below 1, flags augmented events, and appends every gap to
`data/arb.jsonl`. Nothing is traded.

## 6. Research and backtests

All research writes trading-core audit records (`mode: backtest`), so the
same `trading-core-audit` commands and verdict files judge backtests and runs
([`RESEARCH.md`](RESEARCH.md)).

| Tool | Since | What it gives the operator |
|---|---|---|
| Resolved-market collector (`history`) | 0.1.0 | Resolved binary markets with hourly prices for the last 96 hours, resumable |
| Calibration (`calibrate`) | 0.1.0 | The favourite lane's table (price × hours bins, shrunk win rates) with a train/test split and its sha256 |
| Favourite backtest (`backtest favourite`) | 0.1.0 | Calibrates before a split date, replays after it |
| Weather collector (`weather-history`) | 0.1.0 | Resolved temperature events with every bucket's outcome and prices, resumable |
| Weather backtest (`backtest weather`) | 0.1.0 | Day-ahead replay, and with `--intraday` the METAR maximum so far; Brier scores of model, market and blend |
| Station bias (`bias`) | 0.1.0 | Each station's METAR maximum minus the day-ahead forecast |
| METAR archive (`metars`) | 0.1.0 | Keeps METARs beyond AWC's ~15 days so intraday backtests can grow |
| Dry-run recorder (`record`) | 0.1.0 | Each cycle's signals and rejection counts without trading |
| Fed collector (`fed-history`) | 0.2.0 | Settled meetings on both venues: outcomes, Polymarket hourly prices, Kalshi hourly candles (archived events included) |
| Fed backtest (`backtest fed`) | 0.2.0 | Hourly replay with convergence exits; Brier scores of Polymarket, Kalshi and their average at 168/72/24/6/1 h |
| Pair suggestions (`pairs suggest`) | 0.2.0 | Polymarket/Kalshi candidates by title similarity and end date, for review only |
| Reviewed pairs (`pairs approve`, `remove`, `list`) | 0.2.0 | The `crossvenue` lane's pairs file |

## 7. Command line

`trading-polymarket` (since 0.1.0) has twelve commands: `scan`, `weather`,
`record`, `arb`, `bias`, `metars`, `history`, `weather-history`,
`fed-history`, `calibrate`, `backtest` and `pairs`. An API failure is
reported as `error: HTTP …` with exit code 2 (0.2.0). Every flag:
[`CLI.md`](CLI.md).

## 8. Free data clients

Since 0.1.0 one paced, retrying HTTP client serves every source, with
counters on the dashboard: Gamma, CLOB, Open-Meteo, Aviation Weather Center,
Google News RSS; Kalshi (read only) since 0.2.0. None needs a key
([`DATA-SOURCES.md`](DATA-SOURCES.md)).
