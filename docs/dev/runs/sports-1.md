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
- **Started (added 2026-11-07):** 2026-11-07 10:38:15 UTC on `v0.5.0`
  (`f0962b37e45fdd00d6f12b3edc4ba21765c53ae1`) and trading-core `v0.7.0`
  (`cceeed4e2c300eba612dedbd4d2699b6b863815e`), venv `polymarket-v0.5.0`,
  host `M-FYRF96W7JH`, as `data/sports-1/RUN.txt` records. **Planned end:**
  about 2026-11-21 10:38 UTC. A false start from 10:35 UTC ran on a first
  `v0.5.0` tag placed on `61a499d` (the code before the release commit,
  which still said 0.4.0); it was stopped after one cycle, its rows moved
  to `data/sports-1-false-start/` unread, and they are not counted.

- **A check added 2026-11-07, before any read (reported, not deciding;
  the verdict above is unchanged):** settled events are reported by time
  from entry to settlement (under 6 h, 6–24 h, over 24 h) with their net per
  dollar, and no conclusion is drawn from the first-settled events alone.
  Losing sides of a match can settle sooner than winning comebacks, so an
  early read of the settled events can lean towards losses (an outside
  live-money report, agiprolabs/claude-trading-skills,
  `prediction-market-live-ops`; project note
  `trading-skills-review-2026-11-07`).

## Read-out (added at the end)
