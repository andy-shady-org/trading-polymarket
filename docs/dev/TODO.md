# TODO

Open work only, checked against the code and the records on 2026-10-31.
Finished items move to [`DONE.md`](DONE.md) under the heading they had here;
releases are in [`CHANGELOG.md`](../../CHANGELOG.md).

## 1. Now

- [ ] **Runs:** `weather-1` and `fed-1` (v0.4.0) are pre-registered
      ([`runs/weather-1.md`](runs/weather-1.md), [`runs/fed-1.md`](runs/fed-1.md)).
      First the 0.4.0 smoke run and restart drill (`configs/smoke-0.4.0.json`,
      recorded in `weather-1.md`), then start both. While they run: the daily
      check ([`RUNBOOK.md` §4](RUNBOOK.md#4-daily-check-5-minutes)) and
      `metars` in cron. Read each out when it has its positions (weather 150,
      about seven weeks; fed 60; neither before 3 weeks).
- [ ] **CI:** add the `TRADING_CORE_TOKEN` secret and run the matrix,
      including on the `v0.4.0` tag ([`TESTING.md`](TESTING.md#3-ci)).

## 2. Next

- [ ] **Release `v0.5.0`** (tagged on `f0962b3` and installed 2026-11-07, [`releases/0.5.0.md`](releases/0.5.0.md)): pip-audit and the package build, and CI on the tag
- [ ] **Release `v0.4.0`** (tagged and installed 2026-11-04): pip-audit and the package build, and CI on the tag ([`releases/0.4.0.md`](releases/0.4.0.md))
- [ ] **Evidence:** re-run `weather-history --start 2026-08-01` once to pick
      up the ~60 events the first collection did not reach (it is
      resumable).
- [ ] **Weather lane:** re-fit `today_error_weight` and `intraday_sigma` on
      the METAR archive the runs collect (out of sample for the 0.2.1
      weights), and on the same-day runs the live lane uses rather than
      day-ahead runs.
- [ ] **Weather lane:** replay the intraday collapse: record books and
      METARs during a run (`trading-polymarket record`) and add an intraday
      backtest from them.

- [ ] **FEAT-147** ([`PROPOSED-FEATURES.md`](PROPOSED-FEATURES.md#feat-147-updown-stale-quotes-after-a-spot-move)): part 1 read out 2026-11-07 on three days of `ticks` (stopped 12:41 UTC): **takeable** (89.9% of signals), offset **2.20 s** ([`RESULTS.md`](RESULTS.md#2026-11-07--ticks-on-3-days-feat-147-part-1-takeable-no-maker-seat-at-our-speed-feat-101)). From 2026-11-18: `updown-history --start 2026-11-04 --end 2026-11-18`, then `updown-backtest --rule stale --timestamp-offset 2.20` on that window ([`RUNBOOK.md` §9](RUNBOOK.md#9-research-from-a-release-copy)).
- [ ] **`sports-1`** ([`runs/sports-1.md`](runs/sports-1.md), FEAT-168): running on `v0.5.0` since 2026-11-07 10:38:15 UTC (tmux window `sports`); on about 2026-11-21 10:38 UTC stop it and run `venvs/polymarket-v0.5.0/bin/trading-polymarket sports-gaps-report --input data/sports-1`; EXTEND adds 7 days, to 28 at most. Once it is running cleanly, `data/sports-1-false-start/` and the `-mistagged` release copy and venv can go
- [ ] **Research from the CloddsBot review** ([`PROPOSED-FEATURES.md` §2](PROPOSED-FEATURES.md#2-proposed-with-an-id-2026-10-31)): FEAT-102 first (extend `arb`, then a week of records against the pre-written decision rule), FEAT-101 (the recorder built; the maker study read out 2026-11-05 and 2026-11-07: no maker seat at our speed, [`RESULTS.md`](RESULTS.md#2026-11-07--ticks-on-3-days-feat-147-part-1-takeable-no-maker-seat-at-our-speed-feat-101); only a quote behind the top, which needs depth at each level, is left), FEAT-103 (an hour's backtest; stop if negative after fees). None places an order.

## 3. Later

- [ ] **FEAT-149** ([`DONE.md`](DONE.md#feat-149-library-rows-from-polymarkets-data-lane-rows)): `lane-rows` is released in `v0.5.0`; the sweep's price-dependent fee (`--price-fee-rate`) comes with trading-core's next MINOR (`v0.8.0`). Then sweep each fee rate of `history`, `weather-history` and `fed-history`, and `updown-history` once FEAT-147's offset is decided.
- [ ] **FEAT-153** ([`DONE.md`](DONE.md#feat-153-liquidity-rewards-scan-rewards-scan)): run `rewards-scan` daily for a few days, pick clean, quiet rewarded markets and fold them into the maker study (FEAT-101): record their books for a day and measure adverse selection before believing any estimate.

### 3.1 Weather lane

- [ ] Use the ensemble API's member spread as σ where available.
- [ ] Per-station `peak_hour` from the hourly forecast instead of a constant.
- [ ] Size Kelly from equity, not the fixed `bankroll` setting (needs
      trading-core to expose equity to the module).

### 3.2 Favourite lane

- [ ] Count one observation per *event* (not per token) in calibration, or
      weight by event, to stop correlated multi-outcome events inflating `n`.
- [ ] Calibrate by category (`tags`) once samples allow.

### 3.3 Platform

- [ ] Live execution (`LiveExecutor`) with `py-clob-client-v2` as an optional
      extra, after a Stage 1 GO ([`LIVE-TRADING.md`](../LIVE-TRADING.md)).
- [ ] CLOB market WebSocket for book updates (fewer REST reads, faster marks).
- [ ] Arbitrage executor if `data/arb.jsonl` shows gaps worth it after fees (FEAT-102's decision rule).

### 3.4 Docs

- [ ] Decide whether [`BUGS.md`](BUGS.md) takes the standard's section
      headings (`## TP-<n>: … [RESOLVED]`); its status columns already match
      (ID, Severity, Area, Status, Summary). It is append-only history, so it was left
      as it is on 2026-10-31; `test_suite_layout.py` parses its table.
- [ ] Module docstrings and the example configs' `_comment` still name
      `docs/GO-NO-GO.md`, `docs/PAPER-TRADING.md` and `docs/STRATEGIES.md`
      (pointers now); update them with the next code change.
