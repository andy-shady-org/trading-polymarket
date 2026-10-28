# Configuration

The module is configured by the `module_settings` object of a trading-core
settings file (`configs/paper.example.json`). Every key has a safe default, so
`"module_settings": {}` runs the weather lane in paper mode. **Unknown keys
are errors** at every level: a typo never silently falls back to a default.

Engine keys (`order_size`, `risk`, `breaker`, `exits`, paths, …) are
trading-core's; see its `docs/CONFIGURATION.md`. Recommended engine values for
this module are in `configs/paper.example.json`:

- `exits: {}` and `close_positions_on_shutdown: false` — positions are held to
  resolution and redeemed by the module; selling on a generic stop or at
  shutdown would pay the spread and the fee for nothing;
- `risk.max_loss_per_trade: 0` — a binary position's mark can swing from 0.4
  to 0.05 and back within a day; a per-trade loss cap would sell at the worst
  moment. Exposure is capped by `max_total_exposure`, `max_position_size` and
  the lanes' `max_notional`;
- `paper_starting_balance` equal to `module_settings.bankroll`.

Amounts are USDC. Probabilities and prices are 0–1.

## Top level

| Key | Default | Meaning |
|---|---|---|
| `gamma_url` | `https://gamma-api.polymarket.com` | Gamma API base |
| `clob_url` | `https://clob.polymarket.com` | CLOB API base |
| `http_timeout` | `15.0` | Seconds per request |
| `http_retries` | `3` | Retries on 429 / 5xx / network errors (exponential backoff, `Retry-After` honoured) |
| `http_min_interval` | `0.05` | Minimum seconds between requests to one host |
| `quote_ttl_seconds` | `5.0` | How long an order book is reused for quotes, filters and analysts (execution always re-reads) |
| `market_ttl_seconds` | `120.0` | How long a Gamma market is reused (sells and resolution checks always re-read) |
| `unknown_fee_rate` | `0.07` | Fee rate assumed for a fee-enabled market with no `feeSchedule` (the highest known category rate) |
| `bankroll` | `1000.0` | What lane Kelly sizing is a fraction of; keep equal to the paper balance |
| `max_candidates` | `80` | Candidates the pipeline screens per cycle, all lanes together |
| `exit_at_bid` | `0.0` | Sell a position once its bid reaches this (0: hold to resolution). Off until proven ([`GO-NO-GO.md` §3.6](GO-NO-GO.md#36-features-that-stay-off-until-proven)) |
| `paper` | object | Paper fill model (below) |
| `weather`, `favourite`, `momentum` | objects | Lanes (below) |

## `paper`

| Key | Default | Meaning |
|---|---|---|
| `max_slippage` | `0.02` | Without a signal limit, a buy may walk up to best ask + this, a sell down to best bid − this |
| `price_cap` | `0.99` | No paper buy above this price |
| `min_notional` | `1.0` | Smallest fill in USDC |
| `share_decimals` | `2` | Shares are rounded **down** to this precision (the CLOB's) |

The market's own `orderMinSize` (usually 5 shares) is enforced too.

## Lane keys shared by every lane

| Key | Meaning |
|---|---|
| `enabled` | Whether the lane's scout and analyst run |
| `min_volume_24h`, `min_liquidity` | Market-state filter thresholds (Gamma's `volume24hr`, `liquidityNum`) |
| `max_spread` | Order-book filter: best ask − best bid |
| `min_ask_depth`, `depth_window` | Order-book filter: USDC on the asks within `depth_window` of the best ask |
| `min_edge` | Net edge per share (after the fee) the analyst requires on every level it buys |
| `kelly_fraction` | Fraction of full Kelly used for sizing |
| `min_notional`, `max_notional` | Signal size bounds (USDC) |
| `max_candidates` | Candidates the lane's scout hands to the pipeline per cycle |

## `weather`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | |
| `min_volume_24h`, `min_liquidity` | `0`, `0` | Bucket markets are small; quality is judged on the book |
| `max_spread` | `0.15` | |
| `min_ask_depth` | `2.0` | |
| `depth_window` | `0.03` | |
| `min_edge` | `0.06` | After blending with the market |
| `kelly_fraction` | `0.25` | |
| `min_notional`, `max_notional` | `2.0`, `15.0` | |
| `max_candidates` | `40` | |
| `min_price`, `max_price` | `0.02`, `0.97` | Ask band the lane trades |
| `lead_days` | `1` | Trade events up to this many local days ahead (0: today only) |
| `models` | `["ecmwf_ifs025", "gfs_seamless", "icon_seamless"]` | Open-Meteo models averaged |
| `sigma_min` | `0.6` | °C uncertainty of the day's maximum at the peak hour |
| `sigma_per_day` | `1.0` | °C added per day before the peak. With ≥ 10 days in the bias table, the curve is rescaled so the station's measured day-ahead error is its value 30 h before the peak |
| `market_weight` | `0.5` | Fair value = (1 − w) × model + w × market mid (TP-1) |
| `max_edge` | `0.25` | A raw model-vs-ask gap above this is a model error, not traded (TP-1) |
| `min_remaining_sigma` | `0.3` | Floor on σ, also used once the day's maximum is observed |
| `peak_hour` | `15` | Local hour by which the daily maximum is usually set |
| `min_local_hour` | `0` | With a value above 0, trade an event only on its own local day from this hour on (and after the day ends): the intraday window where observations decide most buckets |
| `forecast_ttl_seconds` | `1800.0` | Forecast cache per station (Open-Meteo's free allowance is per IP) |
| `metar_ttl_seconds` | `300.0` | METAR cache per station |
| `cities` | `[]` | Allow-list of city names as in the event titles; empty: all |
| `bias_path` | `""` | Bias table from `trading-polymarket bias` (e.g. `data/weather_bias.json`) |
| `max_events` | `200` | Open events read per cycle (100 per Gamma page) |
| `concurrency` | `8` | Stations priced in parallel |

## `favourite`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Needs a calibration file to trade at all |
| `min_volume_24h`, `min_liquidity` | `5000`, `2000` | |
| `max_spread` | `0.03` | |
| `min_ask_depth` | `50.0` | |
| `depth_window` | `0.03` | |
| `min_edge` | `0.01` | |
| `kelly_fraction` | `0.25` | |
| `min_notional`, `max_notional` | `2.0`, `25.0` | |
| `max_candidates` | `40` | |
| `min_price`, `max_price` | `0.80`, `0.97` | Ask band |
| `min_hours`, `max_hours` | `1.0`, `72.0` | Hours to the market's end date |
| `min_samples` | `200` | Observations a calibration cell needs before the lane trades it |
| `calibration_path` | `""` | `data/calibration.json` from `trading-polymarket calibrate` |
| `max_pages` | `3` | Gamma pages (100 markets each) scanned per cycle |
| `exclude_tags` | `[]` | Event tag slugs never traded (e.g. `["sports"]` for fee-heavy categories) |

## `momentum`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Research lane, no claimed edge |
| `min_volume_24h`, `min_liquidity` | `20000`, `5000` | |
| `max_spread` | `0.03` | |
| `min_ask_depth` | `100.0` | |
| `depth_window` | `0.03` | |
| `min_edge` | `0.0` | Unused (no fair value) |
| `kelly_fraction` | `0.25` | Unused |
| `min_notional`, `max_notional` | `2.0`, `5.0` | Every buy is `min_notional` |
| `max_candidates` | `40` | |
| `min_move` | `0.08` | One-hour price change that counts as a move |
| `min_price`, `max_price` | `0.15`, `0.85` | |
| `min_hours` | `24.0` | Skip markets closing sooner |
| `news` | `false` | Record Google News headlines in the last 6 h as a metric |
| `max_pages` | `2` | |

## Files the module reads

| Path (setting) | Written by | Used by |
|---|---|---|
| `weather.bias_path` | `trading-polymarket bias` | weather lane |
| `favourite.calibration_path` | `trading-polymarket calibrate` | favourite lane |
| `trading_polymarket/data/stations.json` (package) | shipped | weather lane (station coordinates) |

There are no environment variables and no secrets: every source is keyless.
