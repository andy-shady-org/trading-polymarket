# TODO

Open work only, checked against the code and the records on 2026-10-31.
Finished items move to [`DONE.md`](DONE.md) under the heading they had here;
releases are in [`CHANGELOG.md`](../../CHANGELOG.md).

## 1. Now

- [ ] **Runs:** keep `weather-0.2.1` and `fed-0.2.1` going: the daily check
      ([`RUNBOOK.md` §4](RUNBOOK.md#4-daily-check-5-minutes)) and `metars`
      in cron. Read each out when it has its positions (weather 150, about
      seven weeks; fed 60; neither before 3 weeks): verdict into
      [`releases/0.2.1.md`](releases/0.2.1.md#read-out), the top of
      [`RESULTS.md`](RESULTS.md) and [`RELEASE-GATE.md` §1](RELEASE-GATE.md#1-current-status).
- [ ] **Release 0.2.1:** record the smoke run and the kill-and-restart drill
      in [`releases/0.2.1.md`](releases/0.2.1.md) (both still "pending"
      there).
- [ ] **CI:** add the `TRADING_CORE_TOKEN` secret and run the matrix,
      including on the `v0.2.1` tag ([`TESTING.md`](TESTING.md#3-ci)).

## 2. Next

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

## 3. Later

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
- [ ] Arbitrage executor if `data/arb.jsonl` shows gaps worth it after fees.

### 3.4 Docs

- [ ] Decide whether [`BUGS.md`](BUGS.md) takes the standard's format
      (status columns ID, Area, Severity, Status, Summary; sections
      `## TP-<n>: … [RESOLVED]`). It is append-only history, so it was left
      as it is on 2026-10-31; `test_suite_layout.py` parses its table.
- [ ] Module docstrings and the example configs' `_comment` still name
      `docs/GO-NO-GO.md`, `docs/PAPER-TRADING.md` and `docs/STRATEGIES.md`
      (pointers now); update them with the next code change.
