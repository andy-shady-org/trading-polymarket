# Bug tracker

Every bug fixed in trading-polymarket gets a row here and a test tagged
`@pytest.mark.regression("<ID>")`.
`trading_polymarket/tests/unit/test_suite_layout.py` fails when a **RESOLVED**
row has no tagged test, or a tag names no row.

IDs are `TP-<n>` (next free: **TP-5**). Bugs in the engine belong in
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
