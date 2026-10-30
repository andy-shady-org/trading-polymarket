# Strategies (lanes)

The module trades through independent **lanes**. Each lane has its own scout
and analyst, its own thresholds (`module_settings.<lane>`), and tags every
trade with its name as the `strategy`, so each one is judged on its own
(`trading-core-audit verdict --strategy <lane>`, [`GO-NO-GO.md`](GO-NO-GO.md)).

| Lane | Default | Edge claimed | Holds until |
|---|---|---|---|
| `weather` | **on** (late-day window in the paper config) | A forecast + live-observation model of a known settlement rule | Resolution |
| `favourite` | off (needs a calibration file) | Favourite–longshot bias, measured on resolved Polymarket markets | Resolution |
| `momentum` | off | None (research lane collecting evidence) | Resolution, or the engine's generic exits if you configure them |
| `fed` | off (Stage 0 inconclusive, see GO-NO-GO) | Polymarket's Fed-decision buckets drifting away from Kalshi's quote for the same meeting, then converging | Convergence (sold), or resolution |
| `crossvenue` | off (needs reviewed pairs) | The same, for any question a human paired across the two venues | Convergence (sold), or resolution |
| arbitrage scanner | record only | Structural (Yes + No < 1, Σ Yes < 1) | Not traded |

Every lane goes through the same pipeline:

```text
scouts (one per enabled lane) ──► market-state filter ──► order-book filter ──► lane router ──► lane analyst ──► Signal
                                   (open? busy enough      (spread, depth near     (by candidate.data["lane"])
                                    for this lane?)         the ask, imbalance)
```

The analyst re-prices on the **live** book and sizes the buy; trading-core's
risk gate then checks it against exposure, position and balance limits before
the module's paper executor walks the book.

## Shared pricing rules

Every lane uses the same arithmetic ([`strategies/common.py`](../trading_polymarket/strategies/common.py)):

- **Net edge per share** held to resolution: `fair − price − fee(price)`, with
  `fee(p) = rate × p(1 − p)` from the market's `feeSchedule` (0 on fee-free
  markets such as weather and geopolitics).
- **Buy plan**: walk the asks from the best price while *each level's own*
  net edge stays ≥ `min_edge`; that level is the limit. Size with fractional
  Kelly on the best level's cost, `kelly_fraction × (p − c)/(1 − c) × bankroll`,
  capped by `max_notional` and by what the book offers inside the limit;
  refuse below `min_notional`.
- **Settlement**: a share pays 1 if its outcome wins. Positions are held to
  resolution and redeemed at 1 or 0 with no fee — selling a 0.98 winner into
  the bids would pay the spread and the taker fee for nothing.

## Weather lane

Polymarket lists, every day, ~50 events "Highest temperature in <City> on
<Date>?", each with about 11 whole-degree buckets. Since October 2026 they
resolve on **the highest routine METAR temperature** at one named airport on
the station's local date: the hourly `T` remark in tenths of °C when present,
else the body's whole-degree group; `SPECI` reports do not count; °F markets
convert and round half up. Those rules are public and the inputs are free,
which is why this lane exists.

### The model

```text
M  = max routine METAR so far today (station local date)     — known, final value ≥ M
R  ~ Normal(μ, σ)  = maximum of the hours still to come
final = max(M, R)

P(final < x) = 0                    if x ≤ M
             = Φ((x − μ) / σ)       otherwise

P(bucket [lo, hi]) = P(final < hi + ½) − P(final < lo − ½)     (bounds converted to °C)
```

- **Before the event day** (and on it until its first METAR):
  - **μ**: the mean of the configured models' forecasts (default ECMWF IFS
    0.25°, GFS, ICON via Open-Meteo) — the daily maximum, or on the day the
    maximum of the *remaining* hourly values — plus the station's measured
    **bias** (METAR max − day-ahead forecast, from `trading-polymarket bias`)
    while those hours still include `peak_hour` (TP-7, TP-11);
  - **σ**: the curve `sigma_min + sigma_per_day × hours-to-peak / 24`
    (`peak_hour` 15:00 local), combined in quadrature with the models'
    spread. With ≥ 10 days of bias history the curve is instead rescaled so
    that 30 hours before the peak (a day-ahead forecast) it equals the
    station's measured day-ahead error, which already contains the models'
    disagreement. Never below `min_remaining_sigma`.
- **On the event day, once METARs exist** (TP-11):
  - **μ** = forecast maximum of the remaining hours + `today_error_weight`
    (0.5) × today's error so far, where today's error is `M` − the forecast
    maximum of the hours already past. How far the forecast has missed today
    carries into the rest of the day; the station's *average* bias does not;
  - **σ** = `intraday_sigma` (0.8 °C).

  Both were measured on the intraday replay (519 events, 12–27 Oct 2026,
  day-ahead runs, both halves of the window). At 15–16 h local the model
  that 0.2.0 traded scored a log-loss of 0.098–0.107 per bucket against the
  market's 0.083–0.087, and put a further rise of ≥ 1 °C at 0.34 where 0.07
  happened. This model scores 0.065–0.071, below the market in both halves,
  with a calibration error on that rise of 0.01–0.05 (0.2.0: 0.10–0.14). The 0.2.0
  model had added up to +1.8 °C of daily-max bias at the peak hour and
  ignored the day's own error.
- **Late in the day** the remaining hours are cooler than what was already
  observed, so `R` falls below `M` and the distribution collapses on the
  observed maximum: buckets below `M` are impossible (their No is worth ~1),
  and the bucket containing `M` becomes near-certain once the peak is past.
  A further rise after the peak is rare (≥ 1 °C after 16:00 local on 7 % of
  days in the replay); the market prices it well, and the 0.2.0 pilot lost
  ten of ten bets that it would happen.
- **One day, one bet**: every event of one day shares that day's weather
  regimes and the same late-day question, so the lane holds at most
  `max_positions_per_day` (3) positions in markets closing on one date
  (TP-12).
- **After the local day** the observed maximum decides; the market resolves
  at the next day's first METAR.

### Guards (TP-1)

The first live scan claimed edges of 35–55 points — a model error, not money.
So:

- `max_edge` (0.25): a raw model-vs-ask gap above it is counted as a
  *disagreement* and never traded;
- `market_weight` (0.5): the fair value is `(1 − w) × model + w × market mid`,
  because the market knows things the model does not;
- `min_edge` (0.06) after the blend, before fees;
- only events whose rules name **METAR** and an ICAO station are traded (TP-2).

### What the backtest can and cannot show

The weather backtest replays the **day-ahead** forecast at local midnight
(`previous_day1` runs: no hindsight) with a rolling bias learnt only from
earlier events. With `--intraday --entry-hour H` it also replays the
observations: the METAR maximum before `H` becomes the floor and the
day-ahead forecast of the remaining hours the mean — the live lane's model —
but only for the last ~15 days, the METAR history AWC keeps. Prices come from
hourly price history (a mid, not the book), so the paper pilot still has to
measure fills.

Every replay prints **Brier scores** for the model, the market price and the
blend over every bucket it priced. The first replays (October 2026):

- the **forecast alone** is not an edge — over August–October (2,458
  trades, −$4,604) the market's Brier score beat the day-ahead model's at
  every entry hour (0.057 vs 0.067 at midnight);
- **late in the local day** (15:00–19:00) the blend of model and market beat
  the market's Brier score in *both* halves of the window (e.g. 0.0255 vs
  0.0296 at 15:00 on the held-out half), but the PnL over 16 days was not
  positive out of sample and the sample is small.

So the paper configuration trades only that late-day window
(`lead_days: 0`, `min_local_hour: 15`), and the paper pilot — not the
backtest — has to show the edge. See [`RESEARCH.md` §6](RESEARCH.md#6-results-log).

### Growing the evidence

AWC keeps ~15 days of METARs. Run `trading-polymarket metars` daily (cron):
it appends new reports to `data/metars/`, and `backtest weather --intraday`
merges that archive in, so the intraday backtest lengthens by a day per day.

## Favourite lane

Across betting and prediction markets, heavy favourites tend to win slightly
more often than their price says and longshots less often (the
favourite–longshot bias; Snowberg & Wolfers 2010; Whelan 2024; the 2025
Kalshi/Polymarket studies listed in `runtime/polymarket/prediction-market-analysis`).
The lane buys tokens priced in `[min_price, max_price]` (0.80–0.97) whose
market closes in `[min_hours, max_hours]` (1–72 h) — but only where a
**calibration table** built from real resolved Polymarket markets says the
token wins more often than its price plus the taker fee:

```text
win_rate(price, hours) = (wins + k × cell_mean_price) / (n + k) + (price − cell_mean_price)
```

cells are price bins × hours-to-close bins; `k = prior_strength` (50) shrinks
thin cells to the market price, and a cell needs `min_samples` (200)
observations before the lane trades it. Without a table every price maps to
itself: no edge, no trades. The calibration trains on markets that closed
**before** a split date and the backtest runs only on markets after it
([`RESEARCH.md`](RESEARCH.md)).

Fees matter here: at 0.90 a 7% category fee costs 0.0063 per share, which can
be the whole edge. Excluding fee-heavy tags (`exclude_tags`) is a lane setting.

## Momentum lane (research)

Buys a small fixed amount (`min_notional`) of the token that moved up at least
`min_move` in the last hour on a busy market, and records the move, the book
and — with `news: true` — the number of Google News headlines in the last six
hours. It claims no edge. It exists so that `trading-core-audit cuts` can test
whether any of those metrics predicts anything; its verdict file uses a 50 bps
exit haircut because, unlike the other lanes, its positions may be sold.

X/Twitter trends are not used: the API is paid. Google News RSS is the free
attention proxy ([`DATA-SOURCES.md`](DATA-SOURCES.md)).

## `fed` and `crossvenue`: Polymarket against Kalshi

Kalshi (a CFTC-regulated exchange) lists many of Polymarket's questions. Its
public market data is free and keyless, so its quote for the **same**
question is a second, independent price: different users, different market
makers, different fees. Both lanes treat it as the fair value and buy on
Polymarket when the ask is below it by at least `min_edge` after
Polymarket's fee ([`strategies/crossvenue.py`](../trading_polymarket/strategies/crossvenue.py)).
**Kalshi is only read, never traded**: there is no hedge leg.

```text
pair source ──► ReferenceScout ──────────► filters ──► ReferenceAnalyst ──► Signal
(matched or      reference per token,                 live Polymarket book,
 reviewed)       Gamma ask prefilter                  same guards, buy plan
```

**Pairs.** A pair says "this Polymarket token pays 1 exactly when this
Kalshi market's Yes (or No) pays 1" ([`pairs.py`](../trading_polymarket/pairs.py)).

- `fed`: matched every cycle, deterministically. Polymarket's "Fed Decision
  in <Month>?" events are found by Gamma public search; Kalshi's
  `KXFEDDECISION` event for the same meeting is the one whose close is
  within 3 days of the Polymarket end date. Buckets map by move:
  `No change` = `Fed maintains rate` (`H0`), `25 bps decrease` = `Cut 25bps`
  (`C25`), `50+ bps decrease` = `Cut >25bps` (`C26`), and the hikes alike.
  Both Yes and No tokens are paired (the No side's reference is
  `1 − Kalshi Yes`). Buckets that do not map one to one (the older
  `25+ bps increase`, `75+ bps decrease`) are not paired.
- `crossvenue`: only pairs in the **reviewed** file `pairs_path`. Look-alike
  markets are not the same bet when the settlement source, cut-off time or
  tie rule differ, so nothing fuzzy is traded: `trading-polymarket pairs
  suggest` lists candidates by title similarity and end date, a human reads
  both venues' rules, and `pairs approve TOKEN TICKER [--side no]` adds the
  ones that really are one question ([`CLI.md`](CLI.md)). The first live
  run of `suggest` shows why: "J.D. Vance wins the 2028 Republican
  nomination" scored high against "J.D. Vance wins the 2028 Iowa caucus".

**Guards.** A reference prices nothing when its spread is wider than
`max_reference_spread`, it traded less than `min_reference_volume`
contracts in 24 h, or it is older than `max_reference_age_seconds`. A gap
above `max_edge` (0.15) is read as "these two markets do not settle the
same way", not as money. `reference: "bid"` prices from Kalshi's bid
instead of its mid (fewer, safer trades). Markets closing within
`min_hours` are skipped.

**Exit.** Every cycle refreshes the reference of every paired token, held or
not. A held position is sold (`converged`) as soon as its Polymarket bid
reaches the Kalshi mid − `convergence_margin`, while the reference is fresh;
otherwise it is held to resolution. Selling pays the spread, so the verdict
rules haircut every exit by 50 bps.

**What the evidence says (2026-10-29, [`RESEARCH.md` §6](RESEARCH.md#6-results-log)).**
Over the 16 settled meetings both venues listed (Dec 2024 – Oct 2026), the
two prices are within ~1 cent on average and **Kalshi is not the better
forecaster**: Polymarket's Brier score is equal or lower at every horizon
from 7 days to 1 hour. The replay still made +$25 on 23 trades by selling
into convergence (holding to resolution instead: −$2.5): the lane earns the
venues' *temporary* disagreements, not a better forecast. That is a small,
capacity-limited edge (a few trades per meeting), and the sample is all
the history there is.

**A trap the guard caught.** Polymarket listed two "Fed Decision in
September?" events for the 2026 meeting; the thin duplicate resolved
`No change` while the Fed hiked 25 bps (and Kalshi's `H25` paid). The
replay skips any meeting the venues settled differently, and the live lane's
volume filters keep thin duplicates out, but the case is why pairs are
matched on rules, not titles.

## Arbitrage scanner (record only)

`trading-polymarket arb` checks, on live books, two structural gaps:

- **binary pair**: `ask(Yes) + ask(No) + fees < 1`;
- **neg-risk set**: in a mutually exclusive event, `Σ ask(Yes_i) + fees < 1`.

It records every gap above `--min-profit` with its depth to `data/arb.jsonl`.
trading-core opens one instrument per signal, so the legs cannot be bought
atomically; the log answers whether a dedicated executor would be worth
building. Augmented neg-risk events (with an "Other" placeholder) are flagged:
their Yes set may be incomplete, so the sum is not a guaranteed payout.

## Ideas not built (and why)

- **Market making / liquidity rewards** (`polymarket_lp_tool`): needs resting
  orders and live signing; revisit after live execution.
- **LLM news analyst** (TradingAgents, AutoPilotPM): costs per call and no
  measured edge; the momentum lane's metrics must first show attention matters.
- **Two-legged cross-venue arbitrage** (buy on one venue, sell on the
  other): needs a Kalshi account and order signing; the `fed` and
  `crossvenue` lanes use Kalshi as a reference price only.
