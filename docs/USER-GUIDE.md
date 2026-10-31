# User guide

trading-polymarket plugs Polymarket into trading-core. It reads markets,
order books, forecasts, observations and Kalshi's quotes from free public
APIs, decides what to buy in independent **lanes**, simulates fills against
the live order book (paper) and redeems positions when markets resolve. Live
order placement is not built in 0.2.1: the path to real money goes through
the capital gate in [`dev/RELEASE-GATE.md`](dev/RELEASE-GATE.md), whose §1
says where each lane stands today.

## 1. Concepts in one minute

- A Polymarket **market** is a yes/no question with two outcome **tokens**.
  A token costs between 0 and 1 USDC and pays 1 USDC if its outcome wins. The
  module trades tokens; buying "No" is how it bets against an outcome.
- **Fees**: takers pay `shares × rate × p(1 − p)`; the rate depends on the
  category (0 for weather and geopolitics, up to 0.07 for crypto).
- **Lanes** (each tags its trades as its `strategy`, so the audit tools
  judge it alone; [`STRATEGY.md`](STRATEGY.md)):
  - `weather`: daily highest-temperature buckets (on by default);
  - `favourite`: near-resolution favourites (needs a calibration; off);
  - `momentum`: research (off);
  - `fed`: Fed-decision buckets priced against Kalshi's quote (off;
    `configs/paper-fed.example.json` turns it on);
  - `crossvenue`: the same for Polymarket/Kalshi pairs a human approved
    (off until pairs are approved).
- **Hold to resolution**: positions are not sold on generic stops; they are
  redeemed at 1 or 0 when the market resolves. Only `fed` and `crossvenue`
  sell early, when the venues converge.
- **Stages**: a lane climbs Stage 0 (evidence: a backtest), Stage 1 (paper),
  Stage 2 (live canary) and Stage 3 (scale-up), one at a time, each on a
  pre-registered verdict.

## 2. Install

trading-core is private and installed first:

```bash
cd ~/projects/git/trading
python3 -m venv .venv && source .venv/bin/activate      # Python 3.11–3.14
pip install -e trading-core
pip install -e "trading-polymarket[dev]"
trading-core modules          # → polymarket, simulated
```

## 3. Look before you trade

```bash
trading-polymarket weather --city London        # model vs market, bucket by bucket
trading-polymarket scan                         # what the enabled lanes would buy now
trading-polymarket scan --lane fed              # one lane only
trading-polymarket arb                          # structural gaps (record only)
```

## 4. Stage 0: build the evidence

```bash
trading-polymarket bias --days 14
trading-polymarket metars                                   # daily, from cron
trading-polymarket weather-history --start 2026-08-01 --end 2026-10-27
trading-polymarket backtest weather                         # day-ahead
trading-polymarket backtest weather --intraday --entry-hour 15
trading-core-audit verdict --path data/backtest/weather.jsonl --rules configs/verdict/weather.json
trading-polymarket fed-history && trading-polymarket backtest fed            # the fed lane (Kalshi reference)
```

Details and the favourite-lane equivalent: [`RESEARCH.md`](RESEARCH.md);
every result so far: [`dev/RESULTS.md`](dev/RESULTS.md).

## 5. Stage 1: paper trade (three weeks or more)

A first paper run from the repository:

```bash
cp configs/paper.example.json configs/paper.json
trading-core check --config configs/paper.json
trading-core run --config configs/paper.json        # writes data/paper/
```

The dashboard shows prices in cents, positions by bucket name, the lanes and
the API health. A **counted** run — one whose verdict decides a stage — runs
from a tagged release copy in the runtime folder, with a pre-registered
config and verdict file; the procedure, the daily check and the read-out are
in [`dev/RUNBOOK.md`](dev/RUNBOOK.md).

## 6. Where everything else is

| Page | For |
|---|---|
| [`STRATEGY.md`](STRATEGY.md) | What each lane does, the weather model, the guards, how a lane is judged |
| [`FEATURES.md`](FEATURES.md) | Everything that is built |
| [`CONFIGURATION.md`](CONFIGURATION.md) | Every `module_settings` key |
| [`ENVIRONMENT.md`](ENVIRONMENT.md) | Environment variables (none are read) |
| [`CLI.md`](CLI.md) | Every command and flag |
| [`RESEARCH.md`](RESEARCH.md) | Collecting data, calibration, backtests |
| [`DATA-SOURCES.md`](DATA-SOURCES.md) | The free APIs, their limits and quirks |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | How the module implements trading-core's contract |
| [`LIVE-TRADING.md`](LIVE-TRADING.md) | What live trading needs |
| [`dev/RELEASE-GATE.md`](dev/RELEASE-GATE.md) | Current status, release gate, capital stages, stop triggers, versioning |
| [`dev/RUNBOOK.md`](dev/RUNBOOK.md) | Operating a run, the runtime folder, reading it out |
| [`dev/RESULTS.md`](dev/RESULTS.md) | Every study, backtest and run, with its verdict |
| [`dev/README.md`](dev/README.md) | The developer pages: tests, bugs, open work, decisions, costs |
