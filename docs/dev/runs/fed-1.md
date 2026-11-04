# Run fed-1

## Pre-registration (written 2026-11-04 13:20 UTC, before the start)

- **Question:** does the fed lane (buy Polymarket's Fed-decision buckets
  below Kalshi's mid, sell on convergence) earn per position after fees on
  live books, in paper?
- **Code:** trading-core `v0.7.0` (`cceeed4e2c300eba612dedbd4d2699b6b863815e`),
  trading-polymarket `v0.4.0` (`da2722376702a00f63bccb135e5dbb75b03a5b7f`),
  from the release copies in `runtimes/polymarket/releases/`, venv
  `polymarket-v0.4.0`. Its own trading-core instance beside `weather-1`
  (own status, audit and breaker).
- **Config:** `configs/fed-1.json`, sha256
  `9ed3417079b966b0933a47e5195a25d97f0f123adbdb6b55bd00385b63cab6e9`. The
  lane, risk and breaker settings are those of `fed-0.2.1`
  (`configs/paper-fed-0.2.1.json`, sha256 `4d91a23e…`); only the comment and
  the data folder (`data/fed-1/`) differ. Fed lane only: edge 0.02–0.15
  against Kalshi's mid, $25 an entry, exits on convergence.
- **Verdict rules:** `configs/verdict/fed-1.json`, sha256
  `a8341b26a0b0081b693af1d5cf58a0a6a26690d499c6dfbe3b69f69c7780959a`
  (`rules_sha256` `4964977089bc5b3d6f5e98b18707635025f0d3a4c45bd470e2d6e53afa30df77`,
  the same rules as `fed-0.2.1`; only the comment differs). GO needs all of:
  - at least 60 closed positions;
  - adjusted net above 0 after a 50 bps haircut on every exit (convergence
    exits sell into the bid);
  - both halves positive (split at the middle by entry time);
  - at least 55% of UTC days positive;
  - positive without the 3 best positions;
  - the 90% bootstrap interval of the mean per position above 0 (10,000
    samples, seed 7).
- **Lane inputs:** none (Kalshi's quote is read live).
- **Started:** `RUN.txt`'s `started_utc`, after the 0.4.0 smoke run and
  restart drill (recorded in [`weather-1.md`](weather-1.md)). **Planned
  end:** 60 closed positions, and not before 3 weeks after `run_started`.
  Fed meetings are few (about four listed at a time), so 60 positions may
  take months; the read-out waits for them.
- **Stage:** the fed lane is at Stage 1 (paper), with the sample-limited
  Stage 0 exception (Stage 0 INCONCLUSIVE, 2026-10-29: every check passed
  except `min_positions`, +$25.08 on 23 trades; `RELEASE-GATE.md` §3.3). GO
  leads to Stage 2, a live canary, which needs live execution built first.
  NO-GO closes the lane in this form.
- **Operating:** `RULES=configs/verdict/fed-1.json bin/run.sh
  configs/fed-1.json polymarket-v0.4.0`. Restarts with `RESUME=1` are
  allowed; no gap over 6 hours (`GO-NO-GO.md` §3.4).
- **Before it:** `fed-0.2.1` (same settings, v0.2.1) stopped early at 2
  closed positions, adjusted −$0.29, not judged
  ([`../releases/0.2.1.md`](../releases/0.2.1.md#read-out)).

## Read-out (added at the end)
