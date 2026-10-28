# Research: collecting evidence before risking anything

Stage 0 of every lane ([`GO-NO-GO.md`](GO-NO-GO.md)) is a backtest on real,
resolved Polymarket markets. The runtime repositories contained no usable
simulation data ([`DATA-SOURCES.md`](DATA-SOURCES.md#runtime-repositories-hints-only)),
so the module collects its own from the free APIs. Everything lands under
`data/` (git-ignored except what you choose to commit).

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
  uncertainty. Rebuild weekly during the pilot and record the sha256.
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

## 5. Dry-run recording and arbitrage logging (during the pilot)

```bash
trading-polymarket record --cycles 288 --interval 300     # 24 h, every 5 min
trading-polymarket arb --pages 10                          # once, or from cron
```

`record` writes each cycle's signals (with entry metrics) and rejection counts
to `data/record/<date>.jsonl` without trading — useful to grow the sample
beyond what the paper engine's risk limits let through. `arb` appends
structural gaps to `data/arb.jsonl`.

## 6. Results log

Record every Stage 0 run here (newest first): window, data size, config,
rules sha256, verdict and the checks that failed. A NO-GO is a result too.

### 2026-10-28 — first collection (0.1.0)

Data collected from the free APIs on 28 October 2026:

- `markets.jsonl`: **4,454** resolved binary markets with total volume ≥
  $10,000, closing 2026-06-02 … 2026-10-25 (spread evenly over 3-day
  windows), hourly prices for the last 96 hours. Fee rates in the sample:
  0.05 (1,551), 0.03 (1,353), 0.04 (1,018), 0 (487), 0.07 (45).
- `weather.jsonl`: 3,124 resolved temperature events, 1 August – 27 October,
  every bucket's hourly Yes price; `weather-intraday.jsonl`: the 757 events
  of 12–27 October that METARs still cover.

**Calibration (train: 3,051 markets closing before 2026-09-15).** The
favourite–longshot bias of the literature is **not** what this sample shows:

| Price | Mean price | Won (6–24 h) | Won (24–72 h) |
|---|---|---|---|
| 0.05–0.10 | 0.073 | 0.107 | 0.103 |
| 0.80–0.85 | 0.825 | 0.771 | 0.785 |
| 0.85–0.90 | 0.874 | 0.817 | 0.818 |
| 0.90–0.93 | 0.915 | 0.875 | 0.865 |
| 0.95–0.97 | 0.960 | 0.925 | 0.903 |
| 0.97–0.99 | 0.982 | 0.997 | 0.995 |

Favourites in 0.80–0.97 won *less* often than priced; longshots at 0.05–0.10
and near-certainties at 0.97–0.99 won more. Tokens of one multi-outcome event
are correlated, so the cell counts overstate the evidence.

**Favourite backtest (test: 1,403 markets closing 2026-09-15 … 2026-10-25,
`--half-spread 0.01`, rules `configs/verdict/favourite.json`).**

| Variant | Trades | Net | Verdict | Failed checks |
|---|---|---|---|---|
| defaults (0.80–0.97, `min_samples` 200) | 5 | −$22 | NO-GO | positions, net, halves, drop-top, bootstrap |
| `max_price` 0.99, `min_samples` 100 | 95 | −$33 | NO-GO | positions, net, halves, drop-top, bootstrap |
| 0.05–0.99, `min_samples` 100 | 746 | −$147 | NO-GO | all but `min_positions` |

On a partial sample earlier the same day the wide variant had shown +$537 on
435 trades — and was already NO-GO because five longshot wins carried it.
On the full out-of-sample window it loses. **The favourite lane stays off.**
What would change that: calibration by category and by event (not by token),
and a re-test on a new window.

**Weather, day-ahead (forecast only).** 3,124 resolved temperature events
(1 August – 27 October; NOAA-rule events before 22 October, METAR after),
3,025 with forecasts, entry at local midnight, default lane settings and the
rolling per-station bias: **2,458 trades, net −$4,604, NO-GO on every
check** (both halves negative, 28% of days positive). Brier over 33,264
priced buckets: model 0.067, market **0.057**, blend 0.059. On the first
six days alone (22–27 October) the same replay had shown +$200 — another
reminder that a short window proves nothing. Later entry hours only widen
the gap (at 14:00: model 0.081, market 0.038). **The day-ahead forecast does
not beat the market; the lane must not trade on it.**

**Weather, intraday (observations + remaining-hours forecast).** 757 events
12–27 October (the 15 days of METARs AWC keeps), entry at local hour H,
default settings. Brier over all priced buckets:

| H | Trades | Net | Model | Market | Blend |
|---|---|---|---|---|---|
| 10 | 495 | −$1,042 | 0.0660 | 0.0535 | 0.0564 |
| 14 | 355 | −$446 | 0.0480 | 0.0391 | 0.0389 |
| 17 | 110 | +$999 | 0.0115 | 0.0093 | **0.0073** |
| 20 | 21 | +$74 | 0.0072 | 0.0033 | 0.0036 |

Split into a training half (12–19 Oct) and a held-out half (20–27 Oct): the
blend beat the market's Brier score at 15:00–19:00 in **both** halves
(held-out 15:00: 0.0255 vs 0.0296; 17:00: 0.0067 vs 0.0094), but the hour
that made the most money in training (17:00, +$982) lost $29 on the held-out
half — **NO-GO** (66 positions; 1 of 8 days positive). Varying σ
(`sigma_min` 1.0–1.5, `min_remaining_sigma` 0.8–1.2) changed nothing material.

**Reading.** Late in the local day the model–market blend is better
calibrated than the market, consistently, but 16 days give too few trades for
that to show up as reliable profit. The evidence cannot grow from free
history (METARs reach back 15 days), only forward. Hence the
*data-limited* exception in [`GO-NO-GO.md` §3.3](GO-NO-GO.md#33-stage-0--backtest-exit-criteria):
the weather lane goes to the paper pilot **restricted to the late-day window**
(`lead_days: 0`, `min_local_hour: 15`), with `trading-polymarket metars`
archiving observations daily so the intraday backtest can be re-run on the
longer window at the end of the pilot.
