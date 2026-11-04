# Data sources

Every source is **free and keyless**. Nothing here needs an account, an API
key or a subscription; when a paid source becomes worth it, it is added as an
optional extra with its own setting and its own evidence
([`dev/RELEASE-GATE.md` §3.6](dev/RELEASE-GATE.md#36-features-that-stay-off-until-proven)).
The project therefore pays for nothing ([`dev/COSTS.md`](dev/COSTS.md)).

## 1. One HTTP client

All requests go through one client ([`clients/http.py`](../trading_polymarket/clients/http.py)):
a `User-Agent` header (Cloudflare answers 403 without one), pacing per host
(`http_min_interval`, default 50 ms), retries with exponential backoff on 429 /
5xx / network errors (honouring `Retry-After`), and counters shown on the
dashboard (`api requests`, `api failures`, `last api error`).

## 2. Polymarket

| Endpoint | Used for | Notes |
|---|---|---|
| `gamma-api.polymarket.com/markets/keyset` | Market listings (favourite, momentum scouts; history) | `limit` ≤ 100; cursor `after_cursor` → `next_cursor`; filters `closed`, `end_date_min`, `end_date_max`, `tag_slug`, `order`, `ascending`. 300 req / 10 s |
| `gamma-api.polymarket.com/events/keyset` | Events with their markets (weather scout, arb, weather history) | 500 req / 10 s |
| `gamma-api.polymarket.com/markets?clob_token_ids=…` | Market by token id (catalogue, resolution checks) | Batches of 20 tokens |
| `gamma-api.polymarket.com/markets?slug=…&closed=true` | Settled Up/Down markets by slug (`updown-history`) | Up to 100 slugs a request; a crypto Up/Down slug is `<asset>-updown-<window>-<start>`, the window's start in Unix seconds. `events[0].eventMetadata` holds `priceToBeat` and `finalPrice` (Chainlink's 60-second average at the start and end) once settled |
| `gamma-api.polymarket.com/public-search?q=` | Text search (fed scout: "Fed Decision in"; fed history) | `events_status=active|closed`, `limit_per_type` |
| `clob.polymarket.com/book?token_id=` | Live order book (quotes, filters, paper fills, exit value) | Bids ascending and asks descending (best **last**); 404 once the market closes. 1500 req / 10 s |
| `data-api.polymarket.com/v2/trades?condition_id=` | Every trade in a market (`updown-history`) | `limit` ≤ 500, newest first; cursor `pagination.next_cursor` while `pagination.has_more`. One row per **taker** order as it filled (wallet, `side`, `outcome_index`, average `price`, `size`, `timestamp` in seconds, `transaction_hash`); makers do not appear. About 1,600 rows per 5-minute BTC market. **`timestamp` is not the fill's time:** it runs a median 2.2 s after the fill on the market WebSocket (p10 1.5 s, p90 2.8 s; 1,302 fills on 2026-11-04, matched by transaction hash). The first version (`/trades`) answers 410 since late October 2026 |
| `wss://ws-subscriptions-clob.polymarket.com/ws/market` | Live books and fills (`ticks`) | Subscribe with `{"assets_ids": [...], "type": "market"}`. Events: `book` (a full snapshot, re-sent often), `price_change` (`price_changes`: `asset_id`, `price`, `size` at that level, `side` `BUY` bid / `SELL` ask, `best_bid`, `best_ask`), `last_trade_price` (`price`, `size`, `side`, `timestamp` ms, `transaction_hash`). One busy BTC 5-minute market sends about 850 `price_change` events a second. Send the text `PING` every few seconds (a socket was closed ~9 s after a connect without one); new markets need a new subscription (`ticks` reconnects each window) |
| `clob.polymarket.com/time` | Server time in seconds (`ticks`' round-trip probe) | A plain number |
| `clob.polymarket.com/rewards/markets/current` | Markets paying liquidity rewards today (`rewards-scan`) | 500 a page, `next_cursor` until `LTE=` (about 30 pages). Per market: `condition_id`, `rewards_max_spread` (cents from the midpoint), `rewards_min_size` (shares), `total_daily_rate` (USD a day; sometimes absent, then the sum of `rewards_config[].rate_per_day`), the reward asset (pUSD, `0xC011…2DFB`). 14,554 markets on 2026-11-04, about $234,000 a day in all: median $5, p90 $32, max $10,000; 9,228 pay $5 or less, 223 pay $100 or more. Usual terms: 20 shares within 4.5 c (6.5 c and 5.5 c are common). Gamma's `rewardsMinSize` / `rewardsMaxSpread` agreed on the 300 best paid. `sampling-simplified-markets` still answers with older terms in USDC.e (`0x2791…4174`): not used |
| `gamma-api.polymarket.com/markets?condition_ids=…` | Market details by condition id (`rewards-scan`) | Repeat the parameter; 50 ids a request keeps the URL near 4 KB. Without `closed` it answers open markets only, ended ones awaiting resolution included |
| `clob.polymarket.com/prices-history` | Price series for research | Give **both** `startTs` and `endTs` (`endTs` alone is a 400); a window of ~3 weeks or more is refused (fed history asks 7 days at a time); `interval=max` returns an empty series at hourly fidelity for long-lived markets |

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

### Spot for crypto Up/Down (research)

`updown-history` reads the asset's one-second candles from Binance's public
market-data mirror, `data-api.binance.vision/api/v3/klines?interval=1s`
(up to 1,000 a request, keyless; `api.binance.com` refuses some locations
with HTTP 451). A second with no trade has no candle. Binance's USDT price
sits about 15 bp from Chainlink's USD start price (median, BTC, 2026-11-02),
and its close-to-open direction matched the settled outcome in 240 of 288
markets that day, so a backtest measures spot moves from Binance's own price
at the start, and takes outcomes from Gamma.

`ticks` reads Binance's live trades from the same mirror,
`wss://data-stream.binance.vision/ws/<symbol>@aggTrade` (`p` price, `E`
event time, `T` trade time, both in ms); `stream.binance.com:9443` is the
main stream and works where port 9443 is open (`--spot-url`). Receive delay
is `rx − T`, with any difference between the clocks.

## 3. Kalshi (reference prices, read only)

Base `https://api.elections.kalshi.com/trade-api/v2` (`kalshi_url`); no
account or key for market data ([`clients/kalshi.py`](../trading_polymarket/clients/kalshi.py)).
trading-polymarket never places an order on Kalshi.

| Endpoint | Used for | Notes |
|---|---|---|
| `/events?series_ticker=&status=open|settled&with_nested_markets=true` | Fed meetings (`KXFEDDECISION`), pair suggestions | `limit` ≤ 200, `cursor` paging. Settled events older than a few weeks come back **without** nested markets (archived) |
| `/markets/{ticker}` | Reviewed pairs' quotes (crossvenue) | `yes_bid_dollars`, `yes_ask_dollars`, `volume_24h_fp`, `close_time`, `result`, `yes_sub_title` |
| `/series/{series}/markets/{ticker}/candlesticks?start_ts=&end_ts=&period_interval=60` | Hourly Yes bid/ask/volume (fed history) | `close_dollars`, `volume_fp`; 404 once archived |
| `/historical/markets?event_ticker=` | Markets of archived events (fed history) | |
| `/historical/markets/{ticker}/candlesticks?…` | Candles of archived markets | `close` (not `close_dollars`), `volume` |

Prices are dollar strings (`"0.6100"`). A side with no orders reads bid `0`
/ ask `1`; the client treats both as missing. Kalshi's book lists bids on
both sides, so a Yes ask is `1 − best No bid`, and a pair's **No** side
reads Kalshi as `bid = 1 − yes_ask`, `ask = 1 − yes_bid`. Older Fed events
title the hold bucket `No change` instead of `Fed maintains rate`; both
map to `H0`.

## 4. Weather

| Source | Used for | Notes |
|---|---|---|
| `aviationweather.gov/api/data/metar?ids=&format=json&hours=` | Observed temperatures (max so far; bias history) | `rawOb` parsed for the `T` remark (tenths of °C) or the body group; `metarType` `SPECI` excluded. About 15 days of history |
| `aviationweather.gov/api/data/stationinfo?ids=` | Station coordinates | Cached in `trading_polymarket/data/stations.json` (48 stations); unknown stations are looked up once |
| `api.open-meteo.com/v1/forecast` | Multi-model hourly and daily forecasts | `models=ecmwf_ifs025,gfs_seamless,icon_seamless`, `timezone=auto` gives the IANA zone. Free tier ≈ 10,000 calls/day per IP: the lane caches each station for `forecast_ttl_seconds` (30 min) |
| `previous-runs-api.open-meteo.com/v1/forecast` | Day-ahead forecasts of past dates (`temperature_2m_previous_day1`), for bias and the backtest | Up to ~92 past days |
| `ensemble-api.open-meteo.com/v1/ensemble` | Ensemble members (client support; not used by the lane yet) | |

A shared cloud IP can exhaust Open-Meteo's daily allowance ("Daily API request
limit exceeded"); run research from your own machine.

## 5. Attention

| Source | Used for | Notes |
|---|---|---|
| `news.google.com/rss/search?q=` | Headlines in the last 6 h (momentum lane metric) | Optional (`momentum.news`) |
| X / Twitter | — | Paid API; not used |
| GDELT | — | Rate-limited (429) during evaluation; not used |

## 6. Runtime repositories (hints only)

`runtime/polymarket/` holds third-party projects used for ideas, never code.
(It is not runtimes/polymarket, the folder counted runs run from:
[`dev/RUNBOOK.md` §1](dev/RUNBOOK.md#1-the-runtime-folder).)

- **PolyWeather** (AGPL): bucket probability idea, city/station map; its
  `probability_training_snapshots.jsonl` has forecasts without outcomes, so it
  is not usable as training data.
- **prediction-market-backtesting** (LGPL): strategy ideas (late favourite,
  final-period momentum, binary pair arbitrage, panic fade).
- **prediction-market-analysis** (MIT): literature on the favourite–longshot
  bias; its 36 GB dataset is not present locally.

None of them contained data usable for simulation, so the module collects its
own from the free APIs above ([`RESEARCH.md`](RESEARCH.md)).
