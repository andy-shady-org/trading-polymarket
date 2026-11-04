# Run weather-1

## Pre-registration (written 2026-11-04 13:20 UTC, before the start)

- **Question:** does the weather lane's late-day model (TP-11: the
  remaining forecast plus today's error against METAR, entries from 15:00
  local) earn per position after fees on live books, in paper?
- **Code:** trading-core `v0.7.0` (`cceeed4e2c300eba612dedbd4d2699b6b863815e`),
  trading-polymarket `v0.4.0` (`da2722376702a00f63bccb135e5dbb75b03a5b7f`),
  from the release copies in `runtimes/polymarket/releases/`, venv
  `polymarket-v0.4.0`.
- **Config:** `configs/weather-1.json`, sha256
  `fc410578d840378f2edc650b1bb4cda69ec1ce833fe1ebb19da21f52670bb72b`. The
  lane, risk and breaker settings are those of `weather-0.2.1`
  (`configs/paper-weather-0.2.1.json`, sha256 `a1b1c001…`); only the comment
  and the data folder (`data/weather-1/`) differ. Weather lane only: at most
  3 positions per closing date, $15 an entry, edge 0.06–0.25 after blending
  with the market (`market_weight` 0.5), `today_error_weight` 0.5,
  `intraday_sigma` 0.8; positions held to resolution, no engine exits.
- **Verdict rules:** `configs/verdict/weather-1.json`, sha256
  `ffe7be1ede83470b4bc7c914f0bc9393c0355476e84c1dc6cd3d7864319953c0`
  (`rules_sha256` `1084bf9edbe1e7b9086bf9b5e904bae3c7c8c1993144315a7b062e4662f7d26d`,
  the same rules as `weather-0.2.1`; only the comment differs). GO needs all
  of:
  - at least 150 closed positions;
  - adjusted net above 0 (no exit haircut: positions resolve, they are not sold);
  - both halves positive (split at the middle by entry time);
  - at least 55% of UTC days positive;
  - positive without the 5 best positions;
  - the 90% bootstrap interval of the mean per position above 0 (10,000
    samples, seed 7).
- **Lane inputs:** `data/weather_bias.json`, sha256
  `25cf042a0d31af0b3bdd67f1353f7bdbbbc9a185a36a7110287cbfb8164602a3`
  (built 2026-10-28). From 15:00 local every station has reported, so the
  table does not price this run's entries; no rebuilds or restarts for it.
- **Started:** `RUN.txt`'s `started_utc`, after the 0.4.0 smoke run and
  restart drill (recorded below). **Planned end:** 150 closed positions
  (about seven weeks at 3 a day), and not before 3 weeks after
  `run_started`.
- **Stage:** the weather lane is at Stage 1 (paper), with the data-limited
  Stage 0 exception (Stage 0 INCONCLUSIVE, 2026-10-28; `RELEASE-GATE.md`
  §3.3). GO leads to Stage 2, a live canary at the smallest size, which
  needs live execution built first (`LIVE-TRADING.md`). NO-GO closes this
  model: a changed model starts again at Stage 0.
- **Operating:** `RULES=configs/verdict/weather-1.json bin/run.sh
  configs/weather-1.json polymarket-v0.4.0`. Restarts with `RESUME=1` are
  allowed; no gap over 6 hours (`GO-NO-GO.md` §3.4); `metars` in cron for
  the read-out's Brier scores.
- **Before it:** `weather-0.2.1` (same settings, v0.2.1) stopped early at 16
  closed positions, 4 won, adjusted −$67.27, not judged
  ([`../releases/0.2.1.md`](../releases/0.2.1.md#read-out)). Nothing in this
  run was changed because of it.

## Smoke run and restart drill (before the start)

To be recorded by the operator: `configs/smoke-0.4.0.json`, 15 cycles; then
`Ctrl-C` mid-cycle and the same command with `RESUME=1`.

## Read-out (added at the end)
