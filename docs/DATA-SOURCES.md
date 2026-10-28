# Data sources

Every source is **free and keyless**. Nothing here needs an account, an API
key or a subscription; when a paid source becomes worth it, it is added as an
optional extra with its own setting and its own GO/No-Go evidence
([`GO-NO-GO.md` §3.6](GO-NO-GO.md#36-features-that-stay-off-until-proven)).

All requests go through one client ([`clients/http.py`](../trading_polymarket/clients/http.py)):
a `User-Agent` header (Cloudflare answers 403 without one), pacing per host
(`http_min_interval`, default 50 ms), retries with exponential backoff on 429 /
5xx / network errors (honouring `Retry-After`), and counters shown on the
dashboard (`api requests`, `api failures`, `last api error`).

## Polymarket

| Endpoint | Used for | Notes |
|---|---|---|
| `gamma-api.polymarket.com/markets/keyset` | Market listings (favourite, momentum scouts; history) | `limit` ≤ 100; cursor `after_cursor` → `next_cursor`; filters `closed`, `end_date_min`, `end_date_max`, `tag_slug`, `order`, `ascending`. 300 req / 10 s |
| `gamma-api.polymarket.com/events/keyset` | Events with their markets (weather scout, arb, weather history) | 500 req / 10 s |
| `gamma-api.polymarket.com/markets?clob_token_ids=…` | Market by token id (catalogue, resolution checks) | Batches of 20 tokens |
| `gamma-api.polymarket.com/public-search?q=` | Text search | `events_status=active|closed` |
| `clob.polymarket.com/book?token_id=` | Live order book (quotes, filters, paper fills, exit value) | Bids ascending and asks descending (best **last**); 404 once the market closes. 1500 req / 10 s |
| `clob.polymarket.com/prices-history` | Price series for research | Give **both** `startTs` and `endTs` (`endTs` alone is a 400); `interval=max` returns an empty series at hourly fidelity for long-lived markets |

Gamma fields the module reads: `id`, `question`, `conditionId`,
`clobTokenIds` / `outcomes` / `outcomePrices` (JSON strings), `bestBid`,
`bestAsk`, `lastTradePrice`, `volume24hr`, `volumeNum`, `liquidityNum`,
`oneHourPriceChange`, `oneDayPriceChange`, `endDate`, `closed`, `active`,
`acceptingOrders`, `negRisk`, `negRiskMarketID`, `orderPriceMinTickSize`,
`orderMinSize`, `feesEnabled`, `feeSchedule`, `feeType`, `groupItemTitle`,
`description`, `events[]` (title, slug, tags).

### Fees

Since the fee change of 30 March 2026 every market carries
`feeSchedule = {"rate", "exponent", "takerOnly", "rebateRate"}`; a taker pays
`shares × rate × (p(1 − p))^exponent` in USDC, rounded to 5 decimals; makers pay
nothing. Observed `feeType`s: `zero_fees` (weather, geopolitics),
`sports_fees_v2` (0.03), `sports_fees_v3` (0.05), `crypto_fees_v2` (0.07). A
market with fees enabled but no schedule is priced at `unknown_fee_rate`
(0.07) so paper is never cheaper than live. Redeeming a resolved position
costs nothing.

### Resolution

A closed market whose `outcomePrices` are exactly `1` and `0` has resolved;
the module quotes it at its payout and redeems positions at the next cycle.
A closed market without final prices is waiting for UMA; positions stay open
(stale quote) until it resolves.

## Weather

| Source | Used for | Notes |
|---|---|---|
| `aviationweather.gov/api/data/metar?ids=&format=json&hours=` | Observed temperatures (max so far; bias history) | `rawOb` parsed for the `T` remark (tenths of °C) or the body group; `metarType` `SPECI` excluded. About 15 days of history |
| `aviationweather.gov/api/data/stationinfo?ids=` | Station coordinates | Cached in `trading_polymarket/data/stations.json` (48 stations); unknown stations are looked up once |
| `api.open-meteo.com/v1/forecast` | Multi-model hourly and daily forecasts | `models=ecmwf_ifs025,gfs_seamless,icon_seamless`, `timezone=auto` gives the IANA zone. Free tier ≈ 10,000 calls/day per IP: the lane caches each station for `forecast_ttl_seconds` (30 min) |
| `previous-runs-api.open-meteo.com/v1/forecast` | Day-ahead forecasts of past dates (`temperature_2m_previous_day1`), for bias and the backtest | Up to ~92 past days |
| `ensemble-api.open-meteo.com/v1/ensemble` | Ensemble members (client support; not used by the lane yet) | |

A shared cloud IP can exhaust Open-Meteo's daily allowance ("Daily API request
limit exceeded"); run research from your own machine.

## Attention

| Source | Used for | Notes |
|---|---|---|
| `news.google.com/rss/search?q=` | Headlines in the last 6 h (momentum lane metric) | Optional (`momentum.news`) |
| X / Twitter | — | Paid API; not used |
| GDELT | — | Rate-limited (429) during evaluation; not used |

## Runtime repositories (hints only)

`runtime/polymarket/` holds third-party projects used for ideas, never code:

- **PolyWeather** (AGPL): bucket probability idea, city/station map; its
  `probability_training_snapshots.jsonl` has forecasts without outcomes, so it
  is not usable as training data.
- **prediction-market-backtesting** (LGPL): strategy ideas (late favourite,
  final-period momentum, binary pair arbitrage, panic fade).
- **prediction-market-analysis** (MIT): literature on the favourite–longshot
  bias; its 36 GB dataset is not present locally.

None of them contained data usable for simulation, so the module collects its
own from the free APIs above ([`RESEARCH.md`](RESEARCH.md)).
