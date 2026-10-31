# Costs

**trading-polymarket pays for nothing.** It has no subscription, no paid data
and no paid API, and a paper run costs nothing to run beyond the machine it
runs on. Record every payment here, in the currency it was paid in, the day
it is made.

Last checked: 2026-10-31.

## 1. Data and APIs

Every source is free and keyless ([`../DATA-SOURCES.md`](../DATA-SOURCES.md),
ADR-002 in [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md)):

| Source | Price | Limit that matters |
|---|---|---|
| Polymarket Gamma API | free, no key | 300 requests / 10 s on market listings, 500 / 10 s on events |
| Polymarket CLOB API | free, no key | 1,500 requests / 10 s on books |
| Kalshi public market data (read only) | free, no key | – |
| Open-Meteo (forecast, previous runs, ensemble) | free tier | ≈ 10,000 calls a day **per IP**: a shared cloud IP can run out, so research runs on the operator's own machine |
| Aviation Weather Center (METARs, stations) | free, no key | keeps about 15 days of METARs (hence the `metars` archive) |
| Google News RSS | free, no key | – |

Not used because they cost money: the X/Twitter API (paid) and paid weather
data. A paid source is added only when a lane's Stage 1 GO is shown to
depend on it ([`RELEASE-GATE.md` §3.6](RELEASE-GATE.md#36-features-that-stay-off-until-proven)).

## 2. What a run costs

| Run | Cost |
|---|---|
| Paper run (Stage 1) | Nothing: no fees are paid (paper fees are simulated), no data is bought |
| Backtest or collection (Stage 0) | Nothing |
| CI (GitHub Actions) | No line item is recorded |

## 3. Costs that will come with live trading

Live trading is not built ([`../LIVE-TRADING.md`](../LIVE-TRADING.md)). A
live canary will put real money at risk in a dedicated wallet (pUSD
collateral, at most $5 a position, [`RELEASE-GATE.md` §3.1](RELEASE-GATE.md#31-stages-per-lane))
and pay the markets' taker fees; that money and those fees are trading
results, recorded in the audit trail, not project costs. Any new payment it
needs (a paid data source, a service) is added here first.
