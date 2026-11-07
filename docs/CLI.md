# Command line

Trading runs through trading-core; research and inspection through
`trading-polymarket`. Every `trading-polymarket` command is read-only towards
Polymarket and Kalshi and uses free, keyless APIs.

## 1. Trading (trading-core)

```bash
trading-core modules                                  # lists "polymarket" once installed
trading-core check --config configs/paper.json        # validate settings (module settings included)
trading-core run --config configs/paper.json [--headless] [--max-cycles N]
trading-core-audit pnl     --path data/paper/audit.jsonl [--group-by strategy|reason|day|instrument]
trading-core-audit cuts    --path data/paper/audit.jsonl --strategy weather --keep 'fair>=0.5'
trading-core-audit verdict --path data/paper/audit.jsonl --rules configs/verdict/weather.json --strategy weather
trading-core-events --path data/paper/events.jsonl [--tail]
```

See trading-core's `docs/CLI.md` and `docs/AUDIT-TOOL.md` for every flag.
`verdict` exits 0 on GO and 1 on NO-GO. Counted runs start through the
runtime's `bin/run.sh` ([`dev/RUNBOOK.md` §1](dev/RUNBOOK.md#1-the-runtime-folder)).

## 2. `trading-polymarket`

`trading-polymarket --version` prints the version (`0.2.1`). Every command
takes `--config FILE`, a trading-core settings file whose `module_settings`
are used, so research sees the same lane settings as the run; without it the
defaults apply ([`CONFIGURATION.md`](CONFIGURATION.md)).

**Exit codes:** 0 ok; 1 nothing to do (`scan` with no lane enabled,
`calibrate` or `backtest` with no collected data); 2 bad input or a failed
request: an unknown option, `pairs approve` without a token and a ticker, an
unreadable file or invalid settings, or an API failure, printed as one
`error: …` line (`error: HTTP …`) instead of a traceback.

### 2.1 Look at the market

| Command | What it does | Flags (default) |
|---|---|---|
| `scan` | Runs the enabled lanes once on live data and prints the signals (lane, market, fair value, average price, edge, size) and the first errors | `--lane NAME` (repeatable; enables only those lanes), `--limit N` (20) |
| `weather` | Model vs market for every open temperature event within `lead_days`: μ, σ, observed maximum, each bucket's model probability, bid and ask | `--city NAME` (repeatable; default all) |
| `arb` | Full-set gaps in neg-risk events on live books (FEAT-102; [`RESEARCH.md` §5](RESEARCH.md#5-dry-run-recording-and-full-set-gaps)): without `--loop`, one pass over every open event and every set's books, printing the `--top` sets closest to a gap (profit a set after fees, the sets worth buying, their profit; `OPEN`, `(augmented)`). With `--loop`, records until `--hours` pass or `Ctrl-C`: events every `--catalogue` seconds, every set every `--sweep`, sets within `--watch-margin` of a gap every `--watch`, open gaps every `--recheck`; one folder a UTC day under `--out` (`gaps.jsonl`, `observations.jsonl.gz`, `sweeps.jsonl`, `catalogue.jsonl`); gaps still open at the stop are written censored. Record-only: no orders | `--loop`, `--hours`, `--out DIR` (`data/arb`), `--pages` (500 Gamma pages), `--min-profit` (0.005 a set), `--qualify` (5 USD, the run length recorded per gap), `--watch-margin` (0.03), `--recheck` (5 s), `--watch` (30 s), `--sweep` (300 s), `--catalogue` (900 s), `--top` (20) |
| `arb-report` | Reads an `arb --loop` recording: per UTC day the sweeps, gaps, qualifying gaps (not augmented, $5 or more of profit on every read for 10 s or more) and augmented gaps; gaps by kind and by the event's first tag; lifetimes, sizes and profits; and FEAT-102's decision (GO, NO-GO, INCONCLUSIVE under 7 covered days; [`dev/runs/arb-1.md`](dev/runs/arb-1.md)). Exit code 1 when nothing is recorded | `--input DIR` (`data/arb`), `--start`, `--end` (UTC days, end exclusive), `--json FILE` (the summary) |
| `record` | Dry-runs the lanes every interval, appending signals and rejection counts to `<out>/<date>.jsonl` | `--lane NAME` (repeatable), `--cycles N` (1), `--interval SECONDS` (300), `--out DIR` (`data/record`) |

### 2.2 Collect data

| Command | What it does | Flags (default) |
|---|---|---|
| `metars` | Appends every station's new METARs to `<out>/<ICAO>.jsonl` (run daily: AWC keeps ~15 days) | `--out DIR` (`data/metars`) |
| `bias` | Per-station forecast bias (METAR max − day-ahead forecast) → a JSON table | `--days N` (14; AWC keeps only ~15 days), `--station ICAO` (repeatable; default all), `--out` (`data/weather_bias.json`) |
| `history` | Resolved binary markets + hourly prices → JSONL (resumable) | `--start`, `--end` (YYYY-MM-DD, UTC, end exclusive; both required), `--min-volume` (1000), `--tag`, `--max-markets` (2000), `--out` (`data/history/markets.jsonl`) |
| `weather-history` | Resolved temperature events + every bucket's prices → JSONL (resumable) | `--start`, `--end` (required), `--city` (repeatable), `--max-pages` (100), `--concurrency` (8 requests in flight), `--out` (`data/history/weather.jsonl`) |
| `updown-history` | Crypto Up/Down markets of one asset and window (FEAT-146): each settled market's outcome, start and end prices and fee, every trade to the second, and the asset's one-second spot closes; one gzipped file a UTC day, written whole; days on disk and days still running are skipped (resumable). A day that cannot be read whole is named at the end and the exit code is 1 | `--asset` (`btc`; `eth`, `sol`, `xrp`, `doge`, `bnb`), `--window` (`5m`; `15m`), `--start`, `--end` (YYYY-MM-DD, UTC, end exclusive; both required), `--concurrency` (6 markets read at once), `--out DIR` (`data/updown`) |
| `updown-backtest` | Replays a pre-registered rule on collected Up/Down markets. `--rule longshot` (FEAT-146): the first buy print of an outcome at or below the cap from a given second is the signal; the entry fills at the next buy print of that outcome in a later second with at least the stake's notional at most the cap + 1 c. `--rule stale` (FEAT-147): the signal is the first second from 240 s at which Binance spot (the one-second candle that ended then) is at or past −1.5 bp from the window's start price toward an outcome whose last print was at or below 5 c; the fill is the first such buy print 2 to 7 s later, in the fill's own time (the data API's time less `--timestamp-offset`). `--rule fade` (FEAT-103): the signal is the first second with 300 to 60 s left at which spot moved under 6 bp over the 60 s before and one side's last print is 0.35 or less (its mirror buys a side at 0.65 or more); the fill is the next buy print of that side in a later second within 5 s, at most 1 c above. All hold to settlement with the taker fee `0.07 × p(1 − p)` a share and never use prints after the window's close. Prints one row per rule (the primary rule first for `stale` and `fade`: entries, win rate, average fill price, return on stake, each half, without the best 1%, binomial p) and the primary rule's verdict (`stale`, `fade`: PASS, FAIL, or INCONCLUSIVE under 200 entries; its 3 s variant must not lose). Exit code 1 when no markets are found | `--rule` (`longshot`; `stale`, `fade`), `--timestamp-offset` (seconds, `stale` and `fade`; 0; `ticks-report` measures it), `--asset` (`btc`), `--window` (`5m`), `--start`, `--end` (both required; the second half starts at their midpoint), `--stake` (5 USDC), `--input DIR` (`data/updown`), `--out` (`data/backtest/updown-<rule>.jsonl`: the primary rule's trades as audit records; every rule's summary in `updown-<rule>.summary.jsonl` beside it) |
| `ticks` | Records, until `--hours` pass or `Ctrl-C` (exit code 130), the current and next Up/Down markets of an asset on Polymarket's market WebSocket (the best bid and ask when a best price changes, or the size at a best ask of 10 c or less; every fill with its transaction hash), the asset's Binance trades (when the price changes), and a round trip to the CLOB's host every 30 s; every row with its local receive time in milliseconds, one folder a UTC day (FEAT-147, FEAT-101). Prints a status line every 5 minutes. Record-only: no orders | `--asset` (`btc`), `--window` (`5m`), `--hours`, `--spot-url` (Binance's stream; default the `data-stream.binance.vision` mirror), `--out DIR` (`data/ticks`) |
| `ticks-report` | Reads a `ticks` recording: Binance's receive delay, the CLOB round trip, the data API's timestamp offset (its trade time less the fill's WebSocket time, matched by transaction hash for markets already over; its median is `updown-backtest --timestamp-offset`), FEAT-147's signals as they happened (how long the stale ask lived against our delay) and the pre-registered decision on FEAT-147 part 1 (at least 3 days; takeable when half the signals are). Exit code 1 when nothing is recorded | `--input DIR` (`data/ticks`), `--start`, `--end` (UTC days, end exclusive; default all), `--offset-markets N` (20; 0 skips the data API) |
| `rewards-scan` | Lists every market paying Polymarket's liquidity rewards today (CLOB `/rewards/markets/current`), takes the `--limit` best paid, reads each one's details (Gamma) and book, and estimates the daily reward of a two-sided quote of `--quote-shares` at `--quote-cents` from the midpoint with Polymarket's scoring, against the shares already resting inside the reward spread (FEAT-153). Writes one JSON line a market and prints them ranked by estimated reward per dollar the quote ties up; markets past their end date (`ended`) and books wider than twice the reward spread (`wide book`) rank last. **One snapshot of each book, not a sampled day, and no adverse selection: it ranks where to look, not what a quote earns.** Record-only | `--limit` (200), `--min-daily-rate` (0 USD a day), `--quote-shares` (the market's minimum size), `--quote-cents` (1), `--show` (30 rows printed), `--out` (`data/rewards/rewards-<UTC time>.jsonl`) |
| `sports-gaps` | Records, until `--hours` pass or `Ctrl-C`, tennis and esports matches listed on both Polymarket and Kalshi (FEAT-168): every listing on either venue with its creation time, each matched pair once, and every `--interval` seconds a row per pair with Polymarket's best bid and ask (the first outcome's book; the second mirrors it) and Kalshi's best Yes bid and ask for each side, with sizes, until 3 h after the scheduled start. One folder a UTC day ([`RESEARCH.md` §4e](RESEARCH.md#4e-sports-listing-time-gaps-feat-168)) | `--hours`, `--interval` (120), `--out` (`data/sports-gaps`) |
| `sports-gaps-report` | Reads a `sports-gaps` recording: every gap (Polymarket's ask plus its fee at least `--gap` below Kalshi's mid, Kalshi's spread at most `--max-kalshi-spread`, at least `--min-notional` at the ask) as events, by sport and by hours after both venues listed the match, settled from Gamma, and `sports-1`'s decision; events to `--out` | `--input` (`data/sports-gaps`), `--gap` (0.02), `--max-kalshi-spread` (0.05), `--min-notional` (5), `--no-settle`, `--out` (`data/backtest/sports-gaps-events.jsonl`) |
| `fed-history` | Settled Fed meetings listed on both venues: every matched bucket's outcome on each venue, Polymarket's hourly Yes price and Kalshi's hourly bid/ask/volume → JSONL (resumable) | `--days N` (history before each close, 14), `--out` (`data/history/fed.jsonl`) |

### 2.3 Calibrate and backtest

| Command | What it does | Flags (default) |
|---|---|---|
| `calibrate` | Builds the favourite lane's calibration table, prints the reliability table and the table's sha256 | `--input` (`data/history/markets.jsonl`), `--split DATE` (train before it; default: the first 70% of markets by close time) or `--all`, `--prior` (50), `--out` (`data/calibration.json`) |
| `backtest favourite` | Calibrates before `--split`, replays after it; audit-format output | `--input` (`data/history/markets.jsonl`), `--split DATE` (default: the first 70% of markets by close time train), `--half-spread` (0.01), `--out` (`data/backtest/favourite.jsonl`) |
| `backtest weather` | Replays the weather lane at `--entry-hour` (local) with day-ahead forecasts; `--intraday` adds the METAR maximum observed so far (AWC's ~15 days plus the `metars` archive); prints Brier scores of model, market and blend | `--input` (`data/history/weather.jsonl`), `--entry-hour` (0), `--intraday`, `--metar-archive DIR` (`data/metars`), `--half-spread` (0.01), `--out` (`data/backtest/weather.jsonl`) |
| `backtest fed` | Replays the `fed` lane hour by hour on that history (Yes and No sides, convergence exit or resolution); prints Brier scores of Polymarket, Kalshi and their average 168/72/24/6/1 h before each close | `--input` (`data/history/fed.jsonl`), `--half-spread` (0.01), `--out` (`data/backtest/fed.jsonl`) |

Backtests print a one-line JSON summary and the exact `trading-core-audit
verdict` command to judge them. Examples are in [`RESEARCH.md`](RESEARCH.md).

### 2.4 Strategy-library rows (FEAT-149)

| Command | What it does | Flags (default) |
|---|---|---|
| `lane-rows` | Writes data already collected as trading-core's strategy-library rows, for `trading-core-lanes sweep`: each outcome token an instrument, a `listing` at its first price point (`resolves_at` the market's end), a `reading` per price point, an `outcome` at settlement; `fed-history` readings carry Kalshi's last closed mid as `reference`; `updown-history` writes each Up/Down side with a `reading` and a `trade` (the taker's wallet, price × shares) per taker trade. Prints the rows written, the markets by fee rate and what it skipped (prices outside (0, 1], points at or after the end, other fee rates) | `--from history\|weather-history\|fed-history\|updown-history` (required), `--input FILE` (or the `updown-history` folder; required), `--out` (a new `.jsonl` or `.jsonl.gz`; required), `--fee-rate R` (keep only markets at that taker rate: one sweep, one rate), `--asset` (`btc`), `--window` (`5m`), `--start` / `--end` (updown days), `--print-offset S` (0: seconds added to every updown print, FEAT-147's offset) |

### 2.5 Cross-venue pairs

| Command | What it does | Flags (default) |
|---|---|---|
| `pairs suggest` | Scores Polymarket's busiest open markets against Kalshi's open markets by title similarity and end date → a JSONL file (nothing is traded from it) | `--pages N` (5 Gamma pages; Kalshi twice as many), `--min-similarity` (0.5), `--max-days-apart` (3), `--limit` (30 printed), `--out` (`data/pairs_suggested.jsonl`) |
| `pairs approve TOKEN TICKER` | Adds a reviewed pair to the crossvenue pairs file | `--side yes\|no` (yes), `--label`, `--pairs FILE` (default `crossvenue.pairs_path`, `data/pairs.json`) |
| `pairs remove TOKEN` | Removes a token's pairs | `--pairs FILE` |
| `pairs list` | Lists the pairs file | `--pairs FILE` |

Example, after reading both venues' rules:

```bash
trading-polymarket pairs suggest
trading-polymarket pairs approve <polymarket token id> <kalshi ticker> --side no --label "same question"
trading-polymarket pairs list
```
