# AGENTS.md

## Claude 5.5 Opus Self-Correction & Continuous Learning

As **Claude 5.5 Opus**, you are required to treat this repository as the Polymarket module of a live trading system and this `AGENTS.md` file as your persistent memory. The module plugs into **trading-core** (the venue-neutral engine in `../trading-core`), and its purpose is to make money on Polymarket, proven step by step through the gates in `docs/GO-NO-GO.md`. You must automatically update your own rules, adapt to edge cases, and self-correct based on runtime or user feedback.

### 1. Triggers for Updates
You must automatically append a new rule to the **"Local Norms"** or **"Learnings Log"** sections of this file if:
- **User Correction:** The user corrects your pricing, fee or settlement math, a lane's logic, the gates, or the layout.
- **Venue Surprises:** A Polymarket API behaves differently from what `docs/DATA-SOURCES.md` says (a field, a limit, an endpoint, a resolution rule).
- **Runtime Failures:** A scan, backtest, paper or live run shows a wrong number, an implausible edge, a fill that could not have happened live, or an unredeemed resolution.
- **Test Failures:** A test fails because of an unwritten assumption or missed edge case.
- **Stale Context:** A file path, codebase map, document or dependency listed here is outdated.

### 2. Instructions for Self-Updating
1. **Identify the Root Cause:** Pinpoint exactly what went wrong.
2. **Draft a Durable Rule:** A concise "Do" or "Don't" that prevents it permanently.
3. **Modify the File:** Append the rule to the end of the right section. Never erase existing rules.
4. **Keep it Concise:** Short and punchy.

---

## Local Norms
- **A Module, Not An Engine:** Risk, the breaker, positions, accounting, the audit trail and the dashboard belong to trading-core. This package only implements `TradingModule` and its lanes; if the contract cannot express something, change trading-core (with a default and docs), never work around it here.
- **Free Data Only:** Every source is keyless and free (`docs/DATA-SOURCES.md`). A paid or keyed source is an optional extra with its own setting and its own GO/No-Go evidence; secrets come only from environment variables.
- **No Read, No Fill:** Paper fills walk a book read with `max_age=0`; a missing book refuses. A paper fill must never succeed where a live one would not (min size, tick, closed market, limit).
- **Paper Is Never Cheaper Than Live:** Fees come from each market's `feeSchedule`; a fee-enabled market without one is priced at `unknown_fee_rate`. Never default a fee to zero.
- **Hold To Resolution:** Positions redeem at 1 or 0 with no fee. Generic stops, loss caps and shutdown liquidation stay off in configs unless a lane's evidence says otherwise.
- **Too Good To Be True Is A Bug:** A model edge above `max_edge` is a model error (TP-1). Blend with the market (`market_weight`) and investigate disagreements before trusting a model.
- **Read The Rules Of Each Market:** Resolution rules change (weather moved from NOAA time series to METAR in October 2026). Parse the rules text; trade only rule shapes the model implements (TP-2).
- **Evidence Before Money:** A lane moves up a stage only on a pre-registered `trading-core-audit verdict` GO (`configs/verdict/<lane>.json`, sha256 recorded). Backtests calibrate on data before a split and test after it.
- **Mirrored Test Layout, 100% Coverage:** Every source module has `tests/unit/<pkg>/test_<m>.py`; integration and property tests in their folders; builders in `tests/support/`. Statement and branch coverage stay at 100% on Python 3.11–3.14. No network in tests: route HTTP through `FakeTransport`.
- **Docs Track Code:** A change to settings, a lane, a CLI command or a gate updates the matching `docs/` page in the same change; `test_config.py` fails on an undocumented setting.
- **Resolving A Bug Means Tagging A Test:** `docs/dev/BUGS.md` row (`TP-<n>`) plus `@pytest.mark.regression("TP-<n>")`.
- **Never Touch Other Repos From Here:** Work here never edits `pumpfun-trading`; trading-core changes are made in trading-core (its own tests, docs and changelog).

## Learnings Log & Avoided Mistakes
- **[MODEL] A Grid Is Not A Thermometer:** the first scan's 35–55-point "edges" came from an uncorrected grid forecast (TP-1). Measure per-station bias against the settlement source and shrink towards the market.
- **[RULES] Same City, Different Source:** some temperature events settle on Hong Kong Observatory or Wunderground, not METAR (TP-2). The source in the rules decides whether the model applies.
- **[CACHE] Zero Means Refetch:** `age <= max_age` served the cache at `max_age=0` within one cycle (TP-3). Freshness is `age < max_age`.
- **[API] Cloudflare Wants A User-Agent:** Gamma and CLOB answer 403 to requests without one. Every request goes through `JsonHttp`.
- **[API] prices-history Needs A Window:** `interval=max` returns an empty series at hourly fidelity for long-lived markets, and `endTs` alone is a 400. Ask with both `startTs` and `endTs`.
- **[DATA] Empty Is Not Collected:** 1,190 weather events were stored with empty price series and never re-fetched (TP-4). A collector stores a record only when it has the data the replay needs; check a new dataset's coverage per month before trusting a backtest on it.
- **[EVIDENCE] Score Probabilities, Not Just PnL:** a few hundred binary trades are mostly noise; compare the model's Brier score with the market's on every priced bucket (weather replays print it). A model that does not beat the market's Brier score has no edge to trade, whatever the PnL says.
- **[MODEL] Do Not Count Uncertainty Twice:** a station's measured day-ahead error already contains model disagreement and lead time; rescale the σ curve to it (`lead_sigma`) instead of adding more on top.
- **[API] Shared IPs Share Quotas:** Open-Meteo's free allowance is per IP; the cloud workspace hit "Daily API request limit exceeded". Cache forecasts per station and run research locally.
- **[TYPES] Ship py.typed:** mypy saw trading-core as untyped until it shipped a PEP 561 marker. A library other packages type-check against must ship `py.typed`.
- **[COMPAT] 3.11 Coverage And `continue`:** Python 3.11's tracer missed `continue` lines right after an `await` in a loop. Restructure (return empty, let the evaluator decline) instead of adding pragmas.
- **[EVIDENCE] A Few Longshots Are Not An Edge:** on a partial sample the wide favourite backtest made +$537 on 435 trades yet was NO-GO (without the 5 best positions it lost); on the full out-of-sample window it lost $147. Trust `drop_top`, the bootstrap and a held-out window, not the total — and do not assume the literature's bias holds on this venue.

## Project Overview

`trading-polymarket` is the Polymarket trading module for trading-core. It reads Gamma (markets), CLOB (books, price history), Open-Meteo (forecasts), Aviation Weather Center (METARs) and Google News RSS — all free and keyless — prices markets in independent lanes, simulates fills against the live book, redeems at resolution, and ships the research tools (history collection, calibration, backtests, bias tables, arbitrage logging) whose output trading-core's audit tools judge.

Lanes: **weather** (daily-temperature markets: multi-model forecast + live METAR max-so-far against a known settlement rule; on by default), **favourite** (favourite–longshot bias from a calibration on resolved markets; off until calibrated and backtested), **momentum** (research; off). Live order placement is not implemented; it comes after a lane passes the paper stage.

---

## Package Structure

```text
trading-polymarket/
├── trading_polymarket/
│   ├── module.py        # PolymarketModule (entry point "polymarket")
│   ├── config.py        # module_settings: top level, paper, weather / favourite / momentum lanes
│   ├── markets.py       # Market from Gamma: tokens, resolution, payout
│   ├── book.py          # OrderBook from the CLOB: depth, imbalance, walks
│   ├── fees.py          # FeeSchedule (taker fee formula)
│   ├── catalogue.py     # MarketCatalogue, BookCache
│   ├── execution.py     # PaperExecutor (fills, fees, redemption), LiveExecutor (refuses)
│   ├── calibration.py   # CalibrationTable (price × hours bins, shrunk win rates)
│   ├── clients/         # http (paced, retrying), gamma, clob, weather, news
│   ├── strategies/      # common, filters, weather, favourite, momentum, router
│   ├── research/        # records, history, backtest, weather_backtest, bias, arb, recorder
│   ├── data/            # stations.json
│   ├── cli.py           # trading-polymarket
│   └── tests/           # unit (mirrored), integration, property, support, fixtures
├── configs/             # paper / live examples; verdict/<lane>.json pre-registered rules
└── docs/                # user docs; docs/dev/ for maintainers
```

---

## Documentation Architecture

### 1. User & Operator Manuals (`docs/`)
* [**`docs/USER-GUIDE.md`**](docs/USER-GUIDE.md): Start here.
* [**`docs/STRATEGIES.md`**](docs/STRATEGIES.md): The lanes, the weather model, the guards, ideas not built.
* [**`docs/GO-NO-GO.md`**](docs/GO-NO-GO.md): Release gate, capital stages per lane, stop triggers, release record.
* [**`docs/PAPER-TRADING.md`**](docs/PAPER-TRADING.md): Running and reading out the paper pilot.
* [**`docs/RESEARCH.md`**](docs/RESEARCH.md): Data collection, calibration, backtests, results log.
* [**`docs/CONFIGURATION.md`**](docs/CONFIGURATION.md): Every `module_settings` key.
* [**`docs/CLI.md`**](docs/CLI.md): Every command.
* [**`docs/DATA-SOURCES.md`**](docs/DATA-SOURCES.md): The free APIs, limits, quirks, fees.
* [**`docs/ARCHITECTURE.md`**](docs/ARCHITECTURE.md): How the contract is implemented; one cycle; the fill model.
* [**`docs/LIVE-TRADING.md`**](docs/LIVE-TRADING.md): What live trading needs (not built).

### 2. Developer Artifacts (`docs/dev/`)
* [**`docs/dev/TESTING.md`**](docs/dev/TESTING.md): The gate, CI secret, layout, fakes.
* [**`docs/dev/BUGS.md`**](docs/dev/BUGS.md): TP-n bug tracker.
* [**`docs/dev/TODO.md`**](docs/dev/TODO.md): Open work only.
* [**`CHANGELOG.md`**](CHANGELOG.md): Release notes and release records.

---

## Quality Standards & Testing

* **Python 3.11–3.14**; Ruff, Black, flake8, mypy clean; 100% statement and branch coverage on every version.
* `nox -s lint mypy tests` with trading-core from `TRADING_CORE_SOURCE` (default `../trading-core`).

## Build & Installation

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ../trading-core
pip install -e ".[dev]"
nox -s lint mypy tests
```
