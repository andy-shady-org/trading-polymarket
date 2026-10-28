# Command line

Trading runs through trading-core; research and inspection through
`trading-polymarket`. Every command is read-only towards Polymarket and uses
free, keyless APIs.

## Trading (trading-core)

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
`verdict` exits 0 on GO and 1 on NO-GO.

## `trading-polymarket`

Global: `--version`. Every command takes `--config FILE` (a trading-core
settings file; its `module_settings` are used, so research matches the run).
Exit codes: 0 ok, 1 nothing to do (no lane, no data), 2 bad input.

| Command | What it does | Main flags |
|---|---|---|
| `scan` | Runs the enabled lanes once on live data and prints the signals (fair value, average price, edge, size) | `--lane NAME` (repeatable; enables only those), `--limit N` |
| `weather` | Model vs market for every open temperature event within `lead_days`: μ, σ, observed max, each bucket's model probability, bid and ask | `--city NAME` (repeatable) |
| `record` | Dry-runs the lanes every interval, appending signals and rejection counts to `data/record/<date>.jsonl` | `--cycles N`, `--interval SECONDS`, `--out DIR`, `--lane` |
| `arb` | Record-only scan for binary-pair and neg-risk arbitrage on live books; appends to `data/arb.jsonl` | `--pages N`, `--min-profit`, `--min-size`, `--out` |
| `metars` | Appends every station's new METARs to `data/metars/<ICAO>.jsonl` (run daily: AWC keeps ~15 days) | `--out DIR` |
| `bias` | Per-station forecast bias (METAR max − day-ahead forecast) → `data/weather_bias.json` | `--days N` (≤ 15), `--station ICAO` (repeatable), `--out` |
| `history` | Resolved binary markets + hourly prices → `data/history/markets.jsonl` (resumable) | `--start`, `--end` (YYYY-MM-DD, UTC, end exclusive), `--min-volume`, `--tag`, `--max-markets`, `--out` |
| `weather-history` | Resolved temperature events + every bucket's prices → `data/history/weather.jsonl` (resumable) | `--start`, `--end`, `--city`, `--max-pages`, `--out` |
| `calibrate` | Builds the favourite lane's calibration table and prints the reliability table | `--input`, `--split DATE` or `--all`, `--prior`, `--out` |
| `backtest favourite` | Calibrates before `--split`, replays after it; audit-format output | `--input`, `--split`, `--half-spread`, `--out` |
| `backtest weather` | Replays the weather lane at `--entry-hour` (local) with day-ahead forecasts; `--intraday` adds the METAR maximum observed so far (AWC's ~15 days plus the `metars` archive); prints Brier scores of model, market and blend | `--input`, `--entry-hour`, `--intraday`, `--metar-archive DIR`, `--half-spread`, `--out` |

Backtests print a one-line JSON summary and the exact `trading-core-audit
verdict` command to judge them. Examples are in [`RESEARCH.md`](RESEARCH.md).
