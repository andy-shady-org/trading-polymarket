# Results log

Every Stage 0 study, replay and backtest of trading-polymarket, and what
each counted run showed, with its verdict. Moved here on 2026-10-31 from
`docs/RESEARCH.md` §6 unchanged (only its links were fixed); how the data is
collected and the backtests are run is still in
[`../RESEARCH.md`](../RESEARCH.md), and the rules that judge a result in
[`RELEASE-GATE.md`](RELEASE-GATE.md).

> [!NOTE]
> This log is **newest first**, as it was written. trading-core's
> `docs/dev/DOCUMENTATION.md` §8.3 asks new logs to be oldest first; to keep
> this file in one order, **new entries go at the top** of §2.

Entries before 2026-10-31 use the old names: "Stage 0 – Backtest" for
Stage 0, "pilot" for a counted run, "INCONCLUSIVE – PROCEED" for an
INCONCLUSIVE verdict under a Stage 0 exception
([`RELEASE-GATE.md` §3](RELEASE-GATE.md#3-capital-gate)). A counted run's
own record is in [`runs/`](runs/README.md) (from 2026-10-31) or its release
record in [`releases/`](releases/) (before).

## 1. Index

Newest first; net is in USDC after fees, as the audit tools report it.

| Date | Data | Lane | Config | Positions | Net | Verdict |
|---|---|---|---|---|---|---|
| 2026-10-30 | `weather-intraday.jsonl`, 757 events 12–27 Oct | weather (late-day model study) | candidate means, σ fitted per half | – | – | none: a study; the TP-11 model it chose is replayed in [`releases/0.2.1.md`](releases/0.2.1.md) |
| 2026-10-29 | `fed.jsonl`, 17 meetings Dec 2024 – Oct 2026 | fed | default `fed`, half-spread 0.01 | 23 | +$25.08 | NO-GO on `min_positions` only → Stage 0 INCONCLUSIVE (sample-limited) |
| 2026-10-29 | `pairs suggest`, 53 candidates | crossvenue | – | – | – | none: no backtest possible, no pair approved |
| 2026-10-29 | weather run day 1 (0.1.0) | weather | `configs/paper.json` | 31 buys, 2 resolved | −$23.67 on the 2 resolved | not judged: day 1 void (TP-5..TP-8) |
| 2026-10-28 | `markets.jsonl`, 4,454 markets Jun–Oct | favourite | defaults; `max_price` 0.99; 0.05–0.99 | 5 / 95 / 746 | −$22 / −$33 / −$147 | NO-GO (all three) |
| 2026-10-28 | `weather.jsonl`, 3,124 events Aug–Oct | weather (day-ahead) | defaults, entry at midnight | 2,458 | −$4,604 | NO-GO |
| 2026-10-28 | `weather-intraday.jsonl`, 757 events 12–27 Oct | weather (intraday) | defaults, held-out half at 17:00 | 66 | −$29 | NO-GO → Stage 0 INCONCLUSIVE (data-limited) |

## 2. Results

Record every Stage 0 run here (newest first): window, data size, config,
rules sha256, verdict and the checks that failed. A NO-GO is a result too.

### 2026-10-30 — the late-day weather model, measured (after the 0.2.0 pilot)

**What happened.** Day 1 of the weather 0.2.0 pilot: 10 buys, all one thesis
("the maximum still rises ≥ 1 °C after 15:00 local"), priced at 0.20–0.35 by
the model and 0.05–0.08 by the market. All ten lost; the breaker tripped
(review: `claude/polymarket-pilots-review-2026-10-30.md` in the project).

**Study.** `data/history/weather-intraday.jsonl` (757 events, 12–27 Oct;
519 with day-ahead hourly runs and METARs covering the day) at entry hours
12–21 local; truth = the highest routine METAR from the entry hour on.
Candidate means for the remaining hours' maximum, σ fitted on one half of
the window and scored on the other, both ways round:

| Entry 15–16 h, log-loss per bucket (held-out half) | first half | second half |
|---|---|---|
| market price | 0.087 | 0.083 |
| 0.2.0 model (remaining + bias at the peak, lead-curve σ) | 0.107 | 0.098 |
| remaining forecast, σ fitted | 0.083 | 0.076 |
| remaining + bias, σ fitted | 0.085 | 0.082 |
| remaining + ½ today's error, σ 0.8 | **0.071** | **0.065** |

Today's error (`M` − forecast maximum of the hours gone) carries; the
station bias does not once the day has been observed. With σ 0.8 the
calibration error of "rises ≥ 1 °C" is 0.01–0.05 at 15–20 h; 0.2.0's was
0.10–0.14 (predicted → happened: 0.14 → 0.05, 0.25 → 0.14, 0.34 → 0.07). Replayed through `backtest weather
--intraday` at 15 / 16 / 17 h: model Brier 0.032 / 0.019 / 0.010 (0.2.0) →
0.027 / 0.015 / 0.008 (now), market 0.031 / 0.020 / 0.009. The weights were
chosen on this window, so the next pilot is the out-of-sample test.

### 2026-10-29 — Fed lane Stage 0; weather pilot day 1 (0.2.0)

**Fed lane.** `fed-history --days 14` on 29 October 2026: 17 settled
meetings that both venues listed (Dec 2024 – Oct 2026), 58 matched
buckets. The older Polymarket bucket `25+ bps increase` has no one-to-one
Kalshi market and is not paired. One meeting disagrees: Polymarket's thin
duplicate "Fed Decision in September?" (2026) resolved `No change` while
the Fed hiked and Kalshi's `H25` paid; it is skipped (16 meetings used).

Brier scores over the buckets with both prices (lower is better):

| Hours before close | Buckets | Polymarket | Kalshi | Average | Mean abs gap |
|---|---|---|---|---|---|
| 168 | 34 | 0.01844 | 0.01846 | 0.01842 | 0.0096 |
| 72 | 28 | 0.00646 | 0.00680 | 0.00661 | 0.0061 |
| 24 | 22 | 0.00580 | 0.00646 | 0.00612 | 0.0062 |
| 6 | 22 | 0.00806 | 0.00769 | 0.00785 | 0.0078 |
| 1 | 21 | 0.00854 | 0.01035 | 0.00940 | 0.0091 |

Kalshi is not the better forecaster; the venues sit about a cent apart.

Replay, default `fed` settings (`min_edge` 0.02, reference `mid`,
convergence exit), rules `configs/verdict/fed.json` (sha256
`4964977089bc5b3d…`, full hash in the release record):

| Variant | Trades | Net | Verdict | Failed checks |
|---|---|---|---|---|
| default, half-spread 0.01 | 23 | +$25.08 (adjusted +$23.15) | NO-GO | `min_positions` (23 < 60) only; halves +$5.02 / +$18.13, 67% positive days, +$7.22 without the best 3, bootstrap 90% lower bound +$0.21 per position |
| half-spread 0.02 (Stage 0 +1 c check) | 16 | +$17.89 | – | – |
| half-spread 0.005 / 0.015 | 27 / 19 | +$20.44 / +$15.95 | – | – |
| `reference: bid` | 17 | +$21.45 | – | – |
| `min_edge` 0.03 | 16 | +$24.99 | – | – |
| hold to resolution | 23 | −$2.51 | – | – |

Reading: the PnL comes from selling into convergence; held to resolution
the same entries lose, consistent with the Brier table. The sample is all
the history both venues have, so `min_positions` cannot be met by any
backtest. Stage 0 closes **INCONCLUSIVE – PROCEED (sample-limited)**
([`GO-NO-GO.md` §3.3](RELEASE-GATE.md#33-stage-0--evidence-exit-criteria)):
every other check passes, and so does the +1 c spread check.

**Crossvenue lane.** No backtest is possible (see §4a). The first
`pairs suggest` (8,866 Polymarket and 17,579 Kalshi open markets) returned
53 candidates, mostly 2028 nomination markets (long-dated) and two traps a
title match cannot see (nomination vs Iowa caucus; "by Dec 31 2026" vs
"before 2028"). No pair is approved; the lane stays off.

**Weather pilot, day 1 (0.1.0).** 31 paper buys ($312), 2 resolved sells
(−$15.00, −$8.67). The circuit breaker tripped at 09:01 on a "profit run
retracement" from a **phantom** $3,725 equity peak: one-sided books were
valued at ~1 and the status page showed 0.999 marks on both Yes and No of a
market (TP-5). The day also exposed TP-6 (the analyst trusted the scout's
Gamma ask), TP-7 (the day's bias added to hours after the peak) and TP-8
(the pipeline could buy the other side of a held token). All four touch the
money path, so the pilot's day 1 is **void** and the weather lane restarts
Stage 1 under 0.2.0 ([`GO-NO-GO.md` §3.1](RELEASE-GATE.md#31-stages-per-lane)).
With TP-7 fixed, the intraday sweep's test half at 17:00 local turned from
−$29 to +$159; the blend still beats the market's Brier score at 15–18 h
in both halves.

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
*data-limited* exception in [`GO-NO-GO.md` §3.3](RELEASE-GATE.md#33-stage-0--evidence-exit-criteria):
the weather lane goes to the paper pilot **restricted to the late-day window**
(`lead_days: 0`, `min_local_hour: 15`), with `trading-polymarket metars`
archiving observations daily so the intraday backtest can be re-run on the
longer window at the end of the pilot.
