# TODO

Open work only. Done items go to `CHANGELOG.md`.

## Evidence (before the paper pilot)

- [ ] Re-run `weather-history --start 2026-08-01` once to pick up the ~60
      events the first collection did not reach (it is resumable).
- [ ] Start the 0.2.1 pilots (weather, fed) after the smoke run and the
      restart drill ([`releases/0.2.1.md`](releases/0.2.1.md)); `metars` in cron.

## Weather lane

- [ ] Replay the intraday collapse: record books and METARs during the pilot
      (`trading-polymarket record`) and add an intraday backtest from them.
- [ ] Use the ensemble API's member spread as σ where available.
- [ ] Per-station `peak_hour` from the hourly forecast instead of a constant.
- [ ] Re-fit `today_error_weight` and `intraday_sigma` on the METAR archive
      the pilot collects (out of sample for the 0.2.1 weights), and on the
      same-day runs the live lane uses rather than day-ahead runs.
- [ ] Size Kelly from equity, not the fixed `bankroll` setting (needs
      trading-core to expose equity to the module).

## Favourite lane

- [ ] Count one observation per *event* (not per token) in calibration, or
      weight by event, to stop correlated multi-outcome events inflating `n`.
- [ ] Calibrate by category (`tags`) once samples allow.

## Platform

- [ ] Live execution (`LiveExecutor`) with `py-clob-client-v2` as an optional
      extra, after a Stage 1 GO ([`LIVE-TRADING.md`](../LIVE-TRADING.md)).
- [ ] CLOB market WebSocket for book updates (fewer REST reads, faster marks).
- [ ] Arbitrage executor if `data/arb.jsonl` shows gaps worth it after fees.
- [ ] CI: add the `TRADING_CORE_TOKEN` secret and run the matrix
      ([`TESTING.md`](TESTING.md#ci)).
