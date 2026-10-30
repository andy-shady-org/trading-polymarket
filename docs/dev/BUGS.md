# Bug tracker

Every bug fixed in trading-polymarket gets a row here and a test tagged
`@pytest.mark.regression("<ID>")`.
`trading_polymarket/tests/unit/test_suite_layout.py` fails when a **RESOLVED**
row has no tagged test, or a tag names no row.

IDs are `TP-<n>` (next free: **TP-13**). Bugs in the engine belong in
trading-core's own tracker (`TC-<n>`).

When you fix a bug: add a row (status **RESOLVED**), a section below with
root cause and fix, a tagged test, and a Learnings Log entry in `AGENTS.md`
when the lesson is general.

## Status

| ID | Severity | Area | Status | Summary |
|----|----------|------|--------|---------|
| **TP-1** | High | Strategy / Weather | **RESOLVED** | The first live scan priced 40 weather buckets with "edges" of 0.35–0.55: a raw forecast, without station bias, trusted against the market |
| **TP-2** | High | Strategy / Weather | **RESOLVED** | Temperature events settled by another source (Hong Kong Observatory, Wunderground) were priced against airport METARs |
| **TP-3** | High | Catalogue / Execution | **RESOLVED** | `max_age=0` did not force a market refresh when the clock had not moved, so a sell could miss a resolution |
| **TP-4** | High | Research / Weather history | **RESOLVED** | Weather events were stored with empty price series (and then never re-fetched), so the backtest silently skipped them |
| **TP-5** | Critical | Module / Valuation | **RESOLVED** | One-sided books and another token's price valued positions at ~1: a $3,725 equity peak on $1,000 tripped the breaker |
| **TP-6** | High | Strategy / Weather | **RESOLVED** | Price band, `max_edge` and the market blend used Gamma's stale quotes, not the live book |
| **TP-7** | High | Strategy / Weather | **RESOLVED** | The daily-maximum station bias was added to the evening's remaining hours, fattening the upper tail |
| **TP-8** | Medium | Strategy / Pipeline | **RESOLVED** | Both sides of one bucket were bought when the model moved |
| **TP-9** | High | Clients / Gamma | **RESOLVED** | Positions in markets that had closed were never seen to resolve: Gamma's token lookup returns open markets only |
| **TP-10** | Critical | Module / Health | **RESOLVED** | A flat run went "market data stale" after `health_timeout_seconds` and never entered again |
| **TP-11** | Critical | Strategy / Weather | **RESOLVED** | The late-day model priced a further rise at 20–35 % where ~7 % happens: daily-max bias at the peak hour, today's own error ignored |
| **TP-12** | High | Strategy / Sizing | **RESOLVED** | Ten bets on one day's thesis, each Kelly-sized as if independent |

## TP-1: implausible weather edges taken at face value

**Found:** the first live `scan` (28 Oct 2026). 40 signals, the best claiming
55 points of edge (Miami 86–87°F "No" at 0.27 with a model fair value of
0.82); Chicago's 74–75°F bucket was a 26% chance by the model and 74% by the
market at 06:30 local time.

**Root cause:** the model used Open-Meteo's grid forecast with no per-station
correction and a sigma tuned by hand (0.9 °C). A grid cell is not the airport
thermometer and hourly METARs miss the true peak, so the model was
systematically off at many stations. A gap that large is far likelier to be a
model error than free money - the market prices in forecasts the model has
not seen.

**Fix:** (1) `max_edge` (default 0.25): a raw model-vs-ask gap above it is
counted as a disagreement and skipped, never traded; (2) `market_weight`
(default 0.5): the fair value is a blend of the model and the market mid;
(3) wider default sigma (1.2 °C + 1.0 °C/day); (4) a measured per-station
bias and spread (`trading-polymarket bias`) replace the defaults where at
least 10 days are known. All four are tested in the backtest before any
paper run (docs/GO-NO-GO.md stage 0).

**Test:** `tests/unit/strategies/test_weather.py::test_scout_treats_implausible_gaps_as_model_error`.

## TP-2: non-METAR temperature events priced as if METAR-settled

**Found:** building the station list - 7 of 143 open events (Hong Kong,
Jinan, Zhengzhou, ...) settle on the Hong Kong Observatory or Wunderground,
whose numbers the METAR model does not predict.

**Root cause:** `WeatherEvent.parse` accepted any event with a 4-letter code
in brackets.

**Fix:** live trading requires the rules to name METAR and an ICAO station.
Research may opt in (`legacy=True`) to the pre-October-2026 rules, which name
NOAA's station time series for the same airport.

**Test:** `tests/unit/strategies/test_weather.py::test_event_settled_by_a_non_metar_source_is_skipped`.

## TP-3: a forced market refresh served the cache

**Found:** writing the catalogue tests.

**Root cause:** `MarketCatalogue.get` treated an entry as fresh when
`age <= max_age`; with `max_age=0` and a clock that had not advanced (same
cycle) the cached, unresolved market came back, so a sell placed at
resolution could be refused as "closed and not yet resolved" until the
next cycle. `BookCache` already used `<`.

**Fix:** fresh means `age < max_age`, as in `BookCache`; `max_age=0` always
refetches.

**Test:** `tests/unit/test_catalogue.py::test_catalogue_caches_and_refetches_when_stale`.

## TP-4: weather events stored without prices

**Found:** the first weather backtest traded only the last five days of a
two-month collection: all 1,190 September events had empty price series.

**Root cause:** the collector asked `prices-history` with `interval=max`,
which returns an empty series at hourly fidelity for some markets, and it
stored the event anyway — marking it collected, so a re-run never fetched it
again.

**Fix:** windowed requests (`startTs` / `endTs` around the market's end), and
an event whose buckets all come back empty is reported and not stored.
Events are also fetched ten at a time (about 8× faster).

**Test:** `tests/unit/research/test_weather_backtest.py::test_events_without_prices_are_not_stored`.

## TP-5: one-sided books and other tokens' prices valued positions at ~1

**Found:** day 1 of the weather pilot (28–29 Oct 2026). The circuit breaker
tripped on a "profit run retracement" from an equity peak of **$3,725** on a
$1,000 account; open positions were marked at 0.999 on both the Yes and the
No token of the same bucket (Wellington 19°C, Istanbul 16°C).

**Root cause:** two fall-backs. (1) A quote for a closed market used Gamma's
`lastTradePrice`, which is the *first* token's price, for either token. (2)
`exit_value` fell back to the quote's mark when the book had no bids, and a
book with only a 0.999 ask marks at 0.999. Equity, and so the breaker, saw
money no sale could produce.

**Fix:** `Market.price_of(token)` reads each token's own `outcomePrices`
entry; quotes carry it as `last`. `exit_value`: resolved → payout; closed
awaiting resolution → the token's final price; open → the bids walked net of
the fee, and **0 with no bids**.

**Test:** `tests/unit/test_module.py::test_quotes_and_values_use_each_tokens_own_price`.

## TP-6: the guards judged Gamma's stale quotes, not the live book

**Found:** day 1 of the pilot. Seoul 12°C Yes was bought at 0.7¢ with a
fair value of 0.22: Gamma's ask was 0.12 (so the 0.02 price floor and the
`max_edge` guard passed, and the blend used Gamma's mid), while the live book
was at 0.2¢. Mexico City 24°C No: Gamma 0.51, book 0.22.

**Root cause:** the scout's checks (price band, `max_edge`, market blend) used
Gamma's quotes, which can be minutes old; the analyst re-priced the plan on
the live book but kept the scout's fair value and skipped the checks.

**Fix:** the analyst re-applies the band and the `max_edge` guard to the
live best ask and blends with the live book's mid.

**Test:** `tests/unit/strategies/test_weather.py::test_analyst_rechecks_band_and_guard_on_the_live_book`.

## TP-7: the daily-maximum bias was added to the evening's hours

**Found:** reviewing day 1's entries: buckets above the observed maximum
priced at 2–7¢ were bought at fair values of 0.15–0.35 late in the local day
(Chongqing 17°C at 21:00).

**Root cause:** the station bias measures *observed daily max − forecast
daily max*. On the event day the model forecasts only the remaining hours;
once those no longer include the afternoon peak, adding the daily-max bias
(+1 to +1.5 °C at many stations) lifted the evening forecast towards the
observed maximum and fattened the upper tail.

**Fix:** `applied_bias` adds the bias only while the remaining hours include
the peak (`first_hour <= peak_hour + 1`); the intraday backtest uses the
same rule.

**Test:** `tests/unit/strategies/test_weather.py::test_daily_max_bias_is_not_added_after_the_peak`.

## TP-8: both sides of one bucket were bought

**Found:** day 1: Wellington 29 Oct 19°C — Yes at 04:07, No at 05:31.

**Root cause:** the engine excludes held tokens from the pipeline, but not
their complements; when the model moved, the other side became a candidate.
Holding both sides pays two spreads for a position that cannot win more than
it cost.

**Fix:** `LanePipeline` also excludes the complement of every held token
(`PolymarketModule.complement_of`).

**Test:** `tests/unit/strategies/test_router.py::test_pipeline_never_offers_the_other_side_of_a_held_token`.

## TP-9: closed markets were invisible to the token lookup

**Found:** the 0.2.0 weather pilot. Five positions outlived their markets;
the engine retried their exits every 300 s for days (1,205 `exit_refused`
events) and never redeemed them.

**Root cause:** `GammaClient.markets_by_tokens` asks
`/markets?clob_token_ids=...`, and Gamma answers that query with **open
markets only** unless `closed=true` is passed (and then with closed markets
only; checked against the live API). Once a held market closed, its book went
404 and the refetch found nothing, so the catalogue kept the copy cached
while the market was open: never resolved, never redeemed.

**Fix:** tokens the default query does not return are asked again with
`closed=true`. Closed markets reaching a scout are rejected by
`MarketStateFilter` as before.

**Tests:** `tests/unit/clients/test_gamma.py::test_tokens_of_closed_markets_are_found_by_a_second_pass`,
`tests/unit/test_module.py::test_a_held_token_whose_market_closed_resolves`.

## TP-10: a flat run went stale and never entered again

**Found:** the 0.2.0 Fed pilot. After its only trade it held nothing; the
engine reported "market data stale" exactly 600 s after the last sell and no
lane ran again.

**Root cause:** the module told the engine about market data only in
`get_quote`, which the engine calls for held positions. Flat, nothing was
quoted, so health went stale after `health_timeout_seconds`; stale health
blocks entries, which skips the pipeline, which was the only other thing
reading the venue. Nothing could make the data fresh again.

**Fix:** `PolymarketModule.start` runs a heartbeat: every
`heartbeat_seconds` (default 60) it reads the most traded open market and its
CLOB book and, on success, notifies the engine. Three failed reads in a row
report `polymarket data` degraded; the next good read clears it. Health now
tracks the venue, whether a position is held or not.

**Tests:** `tests/unit/test_module.py::test_heartbeat_keeps_a_flat_module_fresh_and_reports_failures`,
`tests/integration/test_paper_run.py::test_a_flat_run_stays_healthy_and_keeps_entering`.

## TP-11: the late-day weather model over-priced further rises

**Found:** the 0.2.0 weather pilot, day 1. Nine of ten entries at 15:00
local, one at 19:00, all on one thesis: the day's maximum still rises ≥ 1 °C
(Yes on the bucket above the observed maximum, or No on the bucket holding
it). The model said 0.20–0.35, the market 0.05–0.08; all ten lost.

**Root cause:** on the event day μ was the remaining hours' forecast plus
the station's daily-max bias (up to +1.8 °C), and σ came from the lead-time
curve. Two faults:
- `applied_bias` kept the bias while `first_hour <= peak_hour + 1`: at
  15:xx the hours to come start at 16:00, past the peak, and the bias was
  still added (TP-7's cut-off, one hour late);
- more important, the model ignored what the day had shown: how far the
  forecast had already missed today predicts the rest of the day far better
  than the station's average bias. Measured on the intraday replay, the
  0.2.0 model at 15–16 h scored worse than the market (log-loss 0.098–0.107
  vs 0.083–0.087) and put 0.34 on rises that happened 7 % of the time.

**Fix:** after the day's first METAR, μ = the remaining hours' forecast
maximum + `today_error_weight` (0.5) × (observed maximum − forecast maximum
of the hours gone), with no station bias, and σ = `intraday_sigma` (0.8);
both measured (docs/RESEARCH.md §6, 2026-10-30), log-loss 0.065–0.071 at
15–16 h, below the market in both halves of the window. The bias cut-off is
`first_hour <= peak_hour` for the fallback before the first METAR. The
intraday backtest uses the same model.

**Tests:** `tests/unit/strategies/test_weather.py::test_the_bias_stops_once_the_peak_hour_is_past`,
`tests/unit/strategies/test_weather.py::test_late_day_rise_is_priced_from_the_day_itself`.

## TP-12: one day's bets were sized as if independent

**Found:** the same day: ten positions on one day and one thesis took the
whole 10 % daily drawdown; the breaker tripped and liquidated into bids of
0.001–0.003.

**Root cause:** each signal is sized with fractional Kelly on its own edge,
as if the bets were independent. Events settled on one day share its
weather regimes and, late in the day, the same question, so ten quarter-Kelly
bets on one thesis are about 2.5 × full Kelly on it.

**Fix:** a lane setting `max_positions_per_day` (weather 3, others 0 = no
cap): `LanePipeline` drops a signal when the lane already holds that many
positions in markets closing on the same UTC date, counting the signals it
keeps in the same cycle. Held tokens whose lane or closing day is unknown
(after a restart) count against every lane or day.

**Test:** `tests/unit/strategies/test_router.py::test_a_lane_holds_at_most_its_cap_on_one_day`.
