# trading-polymarket

The Polymarket module for trading-core: free market data (Kalshi's quotes
included, read only), book-walking paper fills with real fees, settlement at
resolution, independent lanes, and the research tools that decide — with
pre-registered verdicts — whether a lane is allowed near money. Version
0.2.1; needs trading-core 0.2.0 or later.

## What it does

| Lane | What it trades | Default | Stage |
|---|---|---|---|
| **weather** | Daily highest-temperature buckets, priced from multi-model forecasts plus the live METAR maximum against the published settlement rule | on (paper config: late-day window) | 1, paper |
| **favourite** | Near-resolution favourites where a calibration on resolved markets beats price + fee | off until calibrated | 0: NO-GO |
| **momentum** | Research: sharp moves, with attention metrics | off | research, none |
| **fed** | Fed-decision buckets bought below Kalshi's quote for the same meeting, sold when the venues converge | off (paper config: `paper-fed.example.json`) | 1, paper |
| **crossvenue** | The same for any Polymarket/Kalshi pair a human reviewed (`pairs approve`) | off until pairs are approved | 0, not started |
| arbitrage | Yes + No < 1 and neg-risk Σ Yes < 1, logged only | record only | none |

Stages are the capital gate's (0 Evidence, 1 Paper, 2 Live canary, 3
Scale-up); the evidence and the runs in progress:
[`docs/dev/RELEASE-GATE.md` §1](docs/dev/RELEASE-GATE.md#1-current-status).
Every data source is free and keyless ([`docs/DATA-SOURCES.md`](docs/DATA-SOURCES.md)).
Live order placement is not built in 0.2.1 ([`docs/LIVE-TRADING.md`](docs/LIVE-TRADING.md)).

## Install and run

```bash
pip install -e ../trading-core && pip install -e ".[dev]"
trading-polymarket weather --city London          # model vs market, bucket by bucket
trading-polymarket scan                            # what the lanes would buy now
cp configs/paper.example.json configs/paper.json
trading-core run --config configs/paper.json       # paper trading on the live book
```

## Documentation

| Page | For |
|---|---|
| [`docs/USER-GUIDE.md`](docs/USER-GUIDE.md) | Start here: concepts, install, a first run, every other page |
| [`docs/STRATEGY.md`](docs/STRATEGY.md) | The lanes, their rules, evidence and verdicts |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) · [`docs/CLI.md`](docs/CLI.md) · [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md) | Settings, commands, environment variables |
| [`docs/dev/RELEASE-GATE.md`](docs/dev/RELEASE-GATE.md) · [`docs/dev/RUNBOOK.md`](docs/dev/RUNBOOK.md) · [`docs/dev/RESULTS.md`](docs/dev/RESULTS.md) | Status and gates, operating a run, every result |
| [`docs/dev/README.md`](docs/dev/README.md) | The developer pages |
| [`CHANGELOG.md`](CHANGELOG.md) · [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`SECURITY.md`](SECURITY.md) | Releases, how to contribute, secrets |

Proprietary; private use only (see `LICENSE`).
