# Research: collecting evidence before risking anything

Stage 0 of every lane ([`dev/RELEASE-GATE.md` §3.3](dev/RELEASE-GATE.md#33-stage-0--evidence-exit-criteria))
is a backtest on real, resolved Polymarket markets. The runtime repositories
contained no usable simulation data
([`DATA-SOURCES.md` §6](DATA-SOURCES.md#6-runtime-repositories-hints-only)),
so the module collects its own from the free APIs. Everything lands under
`data/` (git-ignored except what you choose to commit). Every result is in
[`dev/RESULTS.md`](dev/RESULTS.md).

Run research from **your own machine**: Open-Meteo's free allowance is per IP
and a shared cloud IP can be exhausted by other users.

## 1. Collect resolved markets (favourite lane)

```bash
trading-polymarket history --start 2026-06-01 --end 2026-10-26 \
    --min-volume 10000 --max-markets 6000
```

- Lists markets that closed in the window (Gamma `closed=true`, 3-day
  windows), keeps **resolved binary** ones with total volume ≥ `--min-volume`,
  spreads the sample evenly over the windows (`max-markets / windows` each).
- Fetches each first token's hourly prices for the last 96 hours before the
  close (CLOB `prices-history`, explicit `startTs`/`endTs`).
- Appends one JSON line per market to `data/history/markets.jsonl`; re-running
  skips markets already collected, so a collection can be resumed or extended.

## 2. Calibrate (favourite lane)

```bash
trading-polymarket calibrate --split 2026-09-15     # train on markets closing before
trading-polymarket calibrate --all                  # train on everything (for paper/live)
```

Samples each market's price 1, 3, 6, 12, 24, 48 and 72 hours before the close
(last print at or before that moment), for **both** tokens, and counts how
often each won, per price bin × hours bin. Prints the reliability table
(`mean` price vs `won` rate vs the `shrunk` estimate the lane uses) and writes
`data/calibration.json` with its sha256. Without `--split` the first 70% of
markets by close time train and the rest are held out.

Caveat: tokens of the same multi-outcome event are correlated, so cell counts
overstate the independent evidence. The `min_samples` and `prior_strength`
settings are deliberately conservative for that reason.

## 3. Backtest the favourite lane

```bash
trading-polymarket backtest favourite --split 2026-09-15 [--half-spread 0.01]
trading-core-audit verdict --path data/backtest/favourite.jsonl --rules configs/verdict/favourite.json
```

Calibrates on markets closing before `--split`, replays only those after it:
for each market, the first horizon (furthest first) at which the live lane
would have bought — price band, enough calibration samples, calibrated edge
after `--half-spread` and the market's fee ≥ `min_edge` — then holds to
resolution. Sizing is the lane's fractional Kelly on `bankroll`. Records are
trading-core audit records (`mode: backtest`), so every `trading-core-audit`
command reads them.

## 4. Weather: bias table, history and backtest

```bash
trading-polymarket bias --days 14                    # data/weather_bias.json
trading-polymarket weather-history --start 2026-09-01 --end 2026-10-27
trading-polymarket backtest weather [--entry-hour 0] [--half-spread 0.01]
trading-polymarket backtest weather --intraday --entry-hour 16      # last ~15 days only
trading-core-audit verdict --path data/backtest/weather.jsonl --rules configs/verdict/weather.json
```

- **bias**: per station, for every complete local day in the last `--days`
  (AWC keeps ~15 days of METARs): highest routine METAR minus the mean of the
  models' *day-ahead* maxima. Writes `{bias, sd, mae, n}` per station. The
  lane adds `bias` to its forecast and, with `n ≥ 10`, uses `sd` as its base
  uncertainty. Rebuild it weekly during a paper run that uses it and record
  the sha256 ([`dev/RUNBOOK.md` §3.2](dev/RUNBOOK.md#32-run)).
- **weather-history**: resolved temperature events (METAR rules and, for
  research only, the pre-October NOAA time-series rules for the same
  airports) with every bucket's outcome and Yes-price series, to
  `data/history/weather.jsonl`. About 11 price requests per event; a month of
  ~50 cities takes a while.
- **backtest weather**: at local midnight of each event day (`--entry-hour`
  later if set), prices every bucket with the live lane's distribution and
  guards (`market_weight`, `max_edge`, `min_edge`) using the **day-ahead**
  multi-model forecast and a bias learnt only from that station's *earlier*
  events, then holds to resolution. `--intraday` adds the METARs observed
  before `--entry-hour` as the floor and the day-ahead forecast of the
  remaining hours as the mean (the live lane's model); METAR history only
  reaches back ~15 days, and days it does not cover are skipped.
- Every weather replay prints **Brier scores** (model, market, blend) over
  all buckets it priced. A model whose Brier score is not below the market's
  is not an edge, whatever the PnL says.

## 4a. Fed decisions and cross-venue pairs (Kalshi)

```bash
trading-polymarket fed-history                       # data/history/fed.jsonl (resumable)
trading-polymarket backtest fed [--half-spread 0.01]
trading-core-audit verdict --path data/backtest/fed.jsonl --rules configs/verdict/fed.json
trading-polymarket pairs suggest                     # data/pairs_suggested.jsonl, for review
```

- **fed-history**: every settled "Fed Decision in <Month>?" event on
  Polymarket matched to Kalshi's `KXFEDDECISION` event for the meeting
  (archived Kalshi events are read from the historical endpoints). Per
  bucket: both venues' outcomes, Polymarket's hourly Yes price and Kalshi's
  hourly candles for the `--days` before Kalshi's close. About 10 requests
  per bucket.
- **backtest fed**: for each bucket and side, hour by hour, with only the
  last *closed* Kalshi candle, the reference volume of the 24 h before, and
  Polymarket's last price ± `--half-spread`: buy when the live lane would,
  sell at convergence (or hold, with `exit_on_convergence: false`). One round
  trip per token and meeting. Meetings the venues settled differently are
  skipped and counted (`disagreements`).
- The summary's **Brier scores** compare Polymarket (`market`), Kalshi
  (`model`) and their average (`blend`) at fixed hours before the close.
  If Kalshi is not the better forecaster, the lane's edge can only be the
  venues' temporary disagreement, which is what convergence exits harvest.
- **pairs suggest** has no backtest: arbitrary pairs have no history until
  someone pairs them. The `crossvenue` lane's evidence is forward only
  (`record --lane crossvenue`, then paper).

## 5. Dry-run recording and arbitrage logging (during a paper run)

```bash
trading-polymarket record --cycles 288 --interval 300     # 24 h, every 5 min
trading-polymarket arb --pages 10                          # once, or from cron
```

`record` writes each cycle's signals (with entry metrics) and rejection counts
to `data/record/<date>.jsonl` without trading — useful to grow the sample
beyond what the paper engine's risk limits let through. `arb` appends
structural gaps to `data/arb.jsonl`.

## 6. Results log

Moved on 2026-10-31 to [`dev/RESULTS.md`](dev/RESULTS.md) (newest first, as before).
