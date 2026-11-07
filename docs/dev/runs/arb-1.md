# Run arb-1

## Pre-registration (written 2026-11-07 14:10 UTC, before the start)

- **Question:** over a week, are there full-set gaps on Polymarket (a
  neg-risk event's Yes set or No set costing less than it pays, after fees)
  often enough, large enough and lasting long enough that an executor would
  be worth building? (FEAT-102, from the CloddsBot review and Saguillo et
  al., arXiv 2508.03474; [`../DONE.md`](../DONE.md#feat-102-full-set-scanner-both-sides-depth-duration-loop).)
- **Kind:** record-only. Nothing is traded and no engine runs; the verdict
  decides whether a multi-leg executor (a trading-core change of its own)
  is designed.
- **Code:** trading-polymarket `v0.6.0` on trading-core `v0.7.0`, from the
  release copies in `runtimes/polymarket/releases/`, venv
  `polymarket-v0.6.0`. The tag's commit and the sha256 of
  `research/arb.py`, `research/arb_loop.py` and `research/arb_report.py` in
  the release copy go in `data/arb-1/RUN.txt` with the start time
  (`bin/record.sh` writes them).
  Read-out by the same release's `arb-report`.
- **Command:** `bin/record.sh arb-1 polymarket-v0.6.0 arb --loop --hours 192
  --out data/arb-1` (runtimes/polymarket; it writes `RUN.txt` and runs
  `venvs/polymarket-v0.6.0/bin/trading-polymarket` with those arguments), in
  its own tmux window, with every default
  (no `--config`, so a fee-enabled market without a fee schedule is priced at
  `unknown_fee_rate`, 0.07): `--min-profit 0.005`, `--qualify 5`,
  `--watch-margin 0.03`, `--recheck 5`, `--watch 30`, `--sweep 300`,
  `--catalogue 900`, `--pages 500`.
- **What is a set** (`research/arb.py`): an open neg-risk event's Yes set
  (one Yes of every live outcome, pays 1) and No set (one No of every live
  outcome, pays `n − 1`). A set exists only when every listed market is
  tradable or closed and resolved No; in an augmented event unlisted
  placeholders are left out only while its `Other` market is tradable
  (TP-13). Legs are priced on their Yes books (No asks are `1 − bid`), each
  level with its market's taker fee per share.
- **What is a gap:** a read where the most sets that each earn at least
  0.5 c after fees (`max_size`) reach the largest minimum order size of the
  legs. A gap runs from its first open read to its last; each read of an
  open gap is recorded.
- **What counts** (`arb-report`, `research/arb_report.py`): a **qualifying
  gap** is one whose event is not augmented, with a run of consecutive
  reads, each showing at least **$5** of profit at `max_size`, spanning at
  least **10 s** (`run_seconds`). It is counted on the UTC day it was first
  seen. This is FEAT-102's rule, "at least 10 gaps a day of at least $5 each
  at a fillable size, lasting at least 10 s", made exact: "lasting" is read
  as $5 or more on every read for 10 s, so a gap that is worth $5 only
  for an instant does not count.
- **Covered days:** a UTC day counts when at least 240 sweeps finished in it
  (of 288 at one every 5 minutes); partial days at the start and end are
  not covered.
- **Verdict** (`arb_report.verdict`):
  - fewer than 7 covered days: **INCONCLUSIVE** (the recorder did not see
    enough of the market; the same command runs again);
  - **GO** when the covered days average at least 10 qualifying gaps **and**
    at least 5 in 7 of them (⌈5/7 × days⌉) have 10 or more;
  - **NO-GO** otherwise.
- **Reported, not deciding:** gaps by kind and by the event's first tag;
  augmented events' gaps apart; lifetimes, peak sizes and profits; the sum
  of the qualifying gaps' peak profit (an upper bound on what an executor
  that won every one could take); censored gaps; and, for the qualifying
  gaps, the days until their set resolves (its markets' latest end date)
  and the return a year on the money the set ties up (the first read's
  profit over its cost, per year to resolution). The verdict counts gaps as
  FEAT-102's rule does, whatever their horizon; the smoke run's two open
  sets paid 2.5 c and 0.7 c a set on events resolving in 2028 and April
  2027, less than cash earns over that time, so a GO leads to an executor
  design only for the gaps whose return a year clears a bar that design
  sets out first.
- **Planned end:** 192 hours (8 days) from the start, so that 7 full UTC
  days are covered; the recorder stops itself.
- **Stage:** research, before Stage 0. GO leads to a design for a full-set
  executor (multi-leg orders in trading-core, live execution here), with its
  own pre-registered run; NO-GO closes the lead and the strategy ledger says
  so (the gaps are taken by others, or are too small or too short for us).
- **Known limits:**
  - Gamma's events are read every 15 minutes: a set listed or completed in
    between is not seen until the next pass.
  - A gap that opens and closes within the 5-minute sweep on a set more than
    3 c from a gap is missed; one open is re-read every 5 s, so its lifetime
    is known to within about 5 s (a lower bound).
  - The ticks of a sweep (about 1.5 minutes) and of a catalogue pass do not
    hold up the 5 s rechecks, but a read is one HTTP round trip after the
    book changed: a gap that lives under a second is not seen.
  - Fees are each market's own schedule at the time of the catalogue pass;
    a schedule changed in between is priced at the old rate.
  - Polymarket's matching may not fill every leg at the read's prices; a
    record of what the books showed is not a fill.
- **Smoke runs (2026-11-07, from the working copy, before this record; not
  counted):**
  - before the fix of TP-13: 7,285 neg-risk events, 14,532 "full" sets
    (3,830 augmented), a catalogue pass in 190 s and a sweep in 93 s; its 65
    "open" sets were the partial sets TP-13 fixed;
  - after it (from 14:04 UTC): 7,303 neg-risk events, 10,768 full sets (30
    augmented; 1,919 events without one), the catalogue in 195 s, a sweep of
    59,505 books in 62 s with none missing; 2 sets open (2.5 c a set on 321
    sets, $2.89; 0.7 c on 347, $2.11), 126 watched.

## Read-out (added at the end)
