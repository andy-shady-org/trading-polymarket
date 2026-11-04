# Done

Finished work from 2026-10-31; earlier work is in
[`CHANGELOG.md`](../../CHANGELOG.md). Items move here from
[`TODO.md`](TODO.md) under the heading they had there, with the release
they shipped in. This file is appended to, never edited back.

## Evidence (before the paper pilot)

- [x] Start the 0.2.1 pilots (weather, fed) after the smoke run and the
      restart drill ([`releases/0.2.1.md`](releases/0.2.1.md)); `metars` in
      cron. *(v0.2.1; started as the runs `weather-0.2.1` and `fed-0.2.1`,
      [`RELEASE-GATE.md` §1](RELEASE-GATE.md#1-current-status). Moved here
      2026-10-31. Recording the smoke run's and the drill's results is open
      in [`TODO.md`](TODO.md).)*

## Docs

- [x] Docs follow trading-core's `docs/dev/DOCUMENTATION.md`: the standard
      layout, pages and records (2026-10-31, Unreleased; `CHANGELOG.md`
      Docs).

## Next: trading-core 0.7.0 (2026-11-04, 0.3.0)

- [x] **`v0.3.0` on trading-core `v0.7.0`, with trusted loading (trading-core 0.3.0, FEAT-89 / FEAT-90; this repository is under its Needed by):** `v0.3.0` declares `trading-core>=0.3.0,<0.8` (`<0.6` on `main` since 2026-11-03) and is tagged with `git tag -s`; `runtime-trading` has a `modules.toml` (written 2026-10-31) and needs `allowed_signers` with the signing key (trading-core's `SECURITY.md`, "Signed releases"). Its `bin/install-release.sh` already refuses an unsigned tag (`ALLOW_UNSIGNED=1` for the old ones). *(the code part, on `release/v0.3.0`; tested on trading-core `v0.7.0`; the tag and `allowed_signers` are the release's, in `TODO.md`)*

## Up/Down research (2026-11-04, 0.4.0)

- [x] **FEAT-146** ([`PROPOSED-FEATURES.md`](PROPOSED-FEATURES.md#feat-146-updown-trade-backfill-and-late-longshot-backtest)): `updown-history` collected every taker trade of 8,615 BTC 5-minute markets (2026-10-05 to 11-03); `updown-backtest` ran the pre-registered late-longshot rule on them: **NO-GO** (−16.9% on stake over 4,500 entries; [`RESULTS.md`](RESULTS.md)). Recorded in trading-core's master ledger and lessons.

## Runs (2026-11-04)

- [x] **`weather-0.2.1` and `fed-0.2.1` closed** (stopped 2026-11-03 05:57 UTC; closed early, not judged: 16 and 2 positions; [`releases/0.2.1.md`](releases/0.2.1.md#read-out)). Their 0.2.1 smoke run and drill were never recorded. Replaced by `weather-1` and `fed-1` on `v0.4.0`, pre-registered with the same lane settings ([`runs/README.md`](runs/README.md)).
