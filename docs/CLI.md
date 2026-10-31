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
| `arb` | Record-only scan for binary-pair and neg-risk arbitrage on live books; appends to a JSONL file and prints the first 20 | `--pages N` (5), `--min-profit` (0.005), `--min-size` (5.0), `--out` (`data/arb.jsonl`) |
| `record` | Dry-runs the lanes every interval, appending signals and rejection counts to `<out>/<date>.jsonl` | `--lane NAME` (repeatable), `--cycles N` (1), `--interval SECONDS` (300), `--out DIR` (`data/record`) |

### 2.2 Collect data

| Command | What it does | Flags (default) |
|---|---|---|
| `metars` | Appends every station's new METARs to `<out>/<ICAO>.jsonl` (run daily: AWC keeps ~15 days) | `--out DIR` (`data/metars`) |
| `bias` | Per-station forecast bias (METAR max − day-ahead forecast) → a JSON table | `--days N` (14; AWC keeps only ~15 days), `--station ICAO` (repeatable; default all), `--out` (`data/weather_bias.json`) |
| `history` | Resolved binary markets + hourly prices → JSONL (resumable) | `--start`, `--end` (YYYY-MM-DD, UTC, end exclusive; both required), `--min-volume` (1000), `--tag`, `--max-markets` (2000), `--out` (`data/history/markets.jsonl`) |
| `weather-history` | Resolved temperature events + every bucket's prices → JSONL (resumable) | `--start`, `--end` (required), `--city` (repeatable), `--max-pages` (100), `--concurrency` (8 requests in flight), `--out` (`data/history/weather.jsonl`) |
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

### 2.4 Cross-venue pairs

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
