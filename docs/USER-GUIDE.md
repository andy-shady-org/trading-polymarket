# User guide

trading-polymarket plugs Polymarket into trading-core. It reads markets,
order books, forecasts and observations from free public APIs, decides what
to buy in independent **lanes**, simulates fills against the live order book
(paper) and redeems positions when markets resolve. Live order placement is
not implemented yet: the path to real money goes through the gates in
[`GO-NO-GO.md`](GO-NO-GO.md).

## 1. Concepts in one minute

- A Polymarket **market** is a yes/no question with two outcome **tokens**.
  A token costs between 0 and 1 USDC and pays 1 if its outcome wins. The
  module trades tokens; buying "No" is how it bets against an outcome.
- **Fees**: takers pay `shares × rate × p(1 − p)`; the rate depends on the
  category (0 for weather and geopolitics, up to 7% for crypto).
- **Lanes**: `weather` (on by default), `favourite` (needs a calibration),
  `momentum` (research). Each tags its trades so the audit tools judge it alone.
- **Hold to resolution**: positions are not sold on generic stops; they are
  redeemed at 1 or 0 when the market resolves.

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
trading-polymarket arb                          # structural gaps (record only)
```

## 4. Build the evidence (Stage 0)

```bash
trading-polymarket bias --days 14
trading-polymarket metars                                   # daily, from cron
trading-polymarket weather-history --start 2026-08-01 --end 2026-10-27
trading-polymarket backtest weather                         # day-ahead
trading-polymarket backtest weather --intraday --entry-hour 15
trading-core-audit verdict --path data/backtest/weather.jsonl --rules configs/verdict/weather.json
```

Details and the favourite-lane equivalent: [`RESEARCH.md`](RESEARCH.md).

## 5. Paper trade (Stage 1, three weeks or more)

```bash
cp configs/paper.example.json configs/paper.json
trading-core check --config configs/paper.json
trading-core run --config configs/paper.json
```

The dashboard shows prices in cents, positions by bucket name, the lanes and
the API health. The day-to-day procedure and the read-out are in
[`PAPER-TRADING.md`](PAPER-TRADING.md).

## 6. Where everything else is

| Page | For |
|---|---|
| [`STRATEGIES.md`](STRATEGIES.md) | What each lane does, the weather model, the guards |
| [`GO-NO-GO.md`](GO-NO-GO.md) | Release gate, capital stages, stop triggers, release record |
| [`PAPER-TRADING.md`](PAPER-TRADING.md) | Running the pilot and reading it out |
| [`RESEARCH.md`](RESEARCH.md) | Collecting data, calibration, backtests, results log |
| [`CONFIGURATION.md`](CONFIGURATION.md) | Every `module_settings` key |
| [`CLI.md`](CLI.md) | Every command |
| [`DATA-SOURCES.md`](DATA-SOURCES.md) | The free APIs, their limits and quirks |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | How the module implements trading-core's contract |
| [`LIVE-TRADING.md`](LIVE-TRADING.md) | What live trading needs (not built yet) |
| [`dev/TESTING.md`](dev/TESTING.md), [`dev/BUGS.md`](dev/BUGS.md), [`dev/TODO.md`](dev/TODO.md) | Maintainers |
