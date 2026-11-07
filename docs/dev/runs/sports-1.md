# Run sports-1

## Pre-registration (written 2026-11-07 10:40 UTC, before the start)

- **Question:** after a tennis or esports match is listed on both
  Polymarket and Kalshi, does Polymarket offer a side at an ask that, with
  its taker fee, sits at least 2 c below Kalshi's mid often enough, for
  long enough and in enough size to be worth a paper lane, and does buying
  those asks and holding to settlement earn? (FEAT-168, from the
  2026-10-30 cross-venue study's one open lead.)
- **Kind:** record-only. Nothing is traded, no engine runs; the verdict
  decides whether a paper lane is built and pre-registered.
- **Code:** trading-polymarket `v0.5.0` on trading-core `v0.7.0`, from the
  release copies in `runtimes/polymarket/releases/`, venv
  `polymarket-v0.5.0` (corrected 2026-11-07, before the start: this record
  first named a commit of `main`; the operator chose to release first).
  The tag's commit goes in `data/sports-1/RUN.txt` with the start time.
  Read-out by the same release's `sports-gaps-report`.
- **Command:** `venvs/polymarket-v0.5.0/bin/trading-polymarket sports-gaps
  --interval 120 --out data/sports-1`, in its own tmux window (the defaults: Polymarket's tennis and esports leagues
  `atp`, `wta`, `itf`, `cs2`, `dota2`, `val`, `lol`, `codmw`, `mlbb`, `ow`;
  Kalshi's 13 match series in `research/sports_gaps.py`; each pair quoted
  until 3 h after its scheduled start).
- **The rule** (`sports-gaps-report` defaults, `GapRule()`): a **gap** is a
  snapshot where Polymarket's ask for a side plus its fee
  (`rate × p × (1 − p)`, the market's own schedule, 0.05 if it has none) is
  at least 0.02 below Kalshi's mid for that side, Kalshi's spread is at
  most 0.05, and the ask holds at least $5. Consecutive gap snapshots of a
  side are one **event**, entered at the first snapshot's ask and held to
  settlement (Gamma's closed market, prices 1 and 0).
- **Verdict** (`sports_gaps_report.decision`), on the days recorded:
  - fewer than 7 days: too early;
  - fewer than 30 events, fewer than 15 matches, or fewer than 30 settled
    events: **EXTEND** before 28 days, **NO-GO** (too few gaps) at 28;
  - mean net per dollar at or below 0 in either half (split at the middle
    of the recording by the event's first snapshot): **NO-GO**;
  - median ask notional under $20: **NO-GO** (too little to matter);
  - otherwise **GO**.
- **Planned end:** 14 days from the start, extended in 7-day steps to at
  most 28 by an EXTEND.
- **Stage:** research, before Stage 0. GO leads to a pre-registered paper
  lane (a `sports` lane in the module, its own run record); NO-GO closes
  the listing-time lead and the strategy ledger says so.
- **Known limits:** a snapshot every 2 minutes cannot see a gap that
  closes inside that time (the study saw one close within an hour); a
  match one venue lists under a name the other does not share is not
  paired (2026-11-07: 72 of 98 Polymarket matches paired in one cycle,
  none ambiguous); doubles and Kalshi's eSoccer and eBasketball are not
  recorded.

## Read-out (added at the end)
