# trading-polymarket

The Polymarket module for [trading-core](https://github.com/andy-shady-org/trading-core):
free market data, book-walking paper fills with real fees, settlement at
resolution, independent strategy lanes, and the research tools that decide —
with pre-registered GO/No-Go gates — whether a lane is allowed near money.

```bash
pip install -e ../trading-core && pip install -e ".[dev]"
trading-polymarket weather --city London          # model vs market, bucket by bucket
trading-polymarket scan                            # what the lanes would buy now
cp configs/paper.example.json configs/paper.json
trading-core run --config configs/paper.json       # paper trading on the live book
```

| Lane | What it trades | Default |
|---|---|---|
| **weather** | Daily highest-temperature buckets, priced from multi-model forecasts plus the live METAR maximum against the published settlement rule | on (paper config: late-day window) |
| **favourite** | Near-resolution favourites where a calibration on resolved markets beats price + fee | off until calibrated |
| **momentum** | Research: sharp moves, with attention metrics | off |
| arbitrage | Yes + No < 1 and neg-risk Σ Yes < 1, logged only | record only |

- Every data source is free and keyless ([docs/DATA-SOURCES.md](docs/DATA-SOURCES.md)).
- Live order placement is not implemented; it comes after a lane passes the
  paper stage ([docs/GO-NO-GO.md](docs/GO-NO-GO.md), [docs/LIVE-TRADING.md](docs/LIVE-TRADING.md)).
- Start with [docs/USER-GUIDE.md](docs/USER-GUIDE.md).

Proprietary; private use only (see `LICENSE`).
