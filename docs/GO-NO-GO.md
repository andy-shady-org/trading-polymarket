# GO / No-Go Gates

This page decides **when trading-polymarket may ship a release** and **when it
may put more money behind a lane**. It is a reusable checklist, not a log: run
it for every release and every capital stage, then write the outcome into a
release record ([§5](#5-release-record)) and `CHANGELOG.md`.

- How to run the pilot day to day: [`PAPER-TRADING.md`](PAPER-TRADING.md).
- How the evidence is produced: [`RESEARCH.md`](RESEARCH.md).
- What each lane does and why it might make money: [`STRATEGIES.md`](STRATEGIES.md).
- Known defects: [`dev/BUGS.md`](dev/BUGS.md).

There are two independent gates:

| Gate | When it runs | Question it answers |
|---|---|---|
| **Release gate** ([§2](#2-release-gate-every-release)) | Every tagged release, before it runs anywhere that matters | Is this build correct, safe and recoverable? |
| **Capital gate** ([§3](#3-capital-gate)) | Before each stage (backtest → paper → live canary → scale-up), per lane | Does this lane make money after fees, and do the books match? |

A build can pass the release gate and still be held at its stage. **Lanes are
judged one by one**: the weather lane can be live while the favourite lane is
still in paper. A lane only moves up when *its own* gate passes.

---

## 1. Current Status

Update this table whenever a gate run finishes; link the release record.

| Item | Status | Evidence |
|---|---|---|
| Release gate, `0.2.0` | PASS locally (2026-10-29): Ruff, Black, flake8, mypy clean; 100% statement + branch coverage on Python 3.11, 3.12, 3.13 and 3.14 against trading-core 0.2.0. CI on the tag pending | [`dev/releases/0.2.0.md`](dev/releases/0.2.0.md) |
| Release gate, `0.1.0` | PASS locally (2026-10-28): Ruff, Black, flake8, mypy clean; 320 tests, 100% statement + branch coverage on Python 3.11, 3.12, 3.13 and 3.14. CI matrix not yet run (needs the `TRADING_CORE_TOKEN` secret, [`dev/TESTING.md`](dev/TESTING.md)) | `CHANGELOG.md` 0.1.0 |
| Weather lane | **Stage 0: INCONCLUSIVE – PROCEED** (2026-10-28, data-limited exception §3.3): day-ahead NO-GO (2,458 trades Aug–Oct, −$4,604); late-day blend beats the market's Brier score in both halves but PnL out of sample is not positive. Stage 1 started 2026-10-28 under 0.1.0; **day 1 void** (TP-5..TP-8 changed the money path, §3.1): **Stage 1 restarts under 0.2.0**, late-day window only (`lead_days: 0`, `min_local_hour: 15`) | [`RESEARCH.md` §6](RESEARCH.md#6-results-log); [`dev/releases/0.1.0-weather-stage1.md`](dev/releases/0.1.0-weather-stage1.md) |
| Favourite lane | **Stage 0 – Backtest: NO-GO** (2026-10-28): every variant loses out of sample; lane off | [`RESEARCH.md` §6](RESEARCH.md#6-results-log) |
| Momentum lane | Research only, off by default; no stage | – |
| Fed lane | **Stage 0: INCONCLUSIVE – PROCEED (sample-limited)** (2026-10-29, §3.3): every verdict check passes except `min_positions` (23 < 60 — all the history both venues have); +$25.08 on 23 trades, +$17.89 at +1 c spread; Kalshi's Brier score is **not** below Polymarket's, so the edge is convergence, not forecasting. Stage 1 (paper, own instance `paper-fed`) starts with 0.2.0 | [`RESEARCH.md` §6](RESEARCH.md#6-results-log); [`dev/releases/0.2.0.md`](dev/releases/0.2.0.md) |
| Crossvenue lane | **Stage 0: not started** — no history exists for arbitrary pairs; needs reviewed pairs (`pairs approve`), then a recorded dry run (§3.3) | [`STRATEGIES.md`](STRATEGIES.md#fed-and-crossvenue-polymarket-against-kalshi) |
| Arbitrage scanner | Record only; no execution exists | – |
| Live execution | **Not implemented.** Every live order and balance read is refused | [`LIVE-TRADING.md`](LIVE-TRADING.md) |

---

## 2. Release Gate (every release)

Run from a clean checkout of the release commit, with trading-core installed
from the commit you will run with (`TRADING_CORE_SOURCE`, [`dev/TESTING.md`](dev/TESTING.md)).

### 2.1 Code quality
- [ ] `nox -s format` changes nothing
- [ ] `nox -s lint` passes (Ruff, Black, flake8)
- [ ] `nox -s mypy` passes

### 2.2 Tests and coverage
- [ ] `nox -s tests` passes on **every** supported interpreter (3.11, 3.12, 3.13, 3.14) — the CI matrix is the evidence, since local nox skips interpreters that are not installed
- [ ] Coverage is **100%** statements and branches (`fail_under = 100`, never lowered)
- [ ] The collected test count did not fall, unless the release notes say why
- [ ] Every bug resolved in the release has a `docs/dev/BUGS.md` row and a `@pytest.mark.regression("TP-<n>")` test (the layout test enforces it)

### 2.3 Trading behaviour
- [ ] `trading-polymarket scan` on live data runs without errors and its signals look sane (no edge above `max_edge`, prices in cents, sizes within the lane caps)
- [ ] The paper round trip (buy → resolution → redeem) is exercised by `tests/integration/test_paper_run.py` and passes
- [ ] Any change to fees, book walking, settlement or sizing re-runs the backtests ([`RESEARCH.md`](RESEARCH.md)) and the release record states the before/after numbers
- [ ] Any change to the weather model's parsing is checked against the **current** resolution rules of a live event (they changed in October 2026, TP-2)

### 2.4 Security
- [ ] No secrets in tracked files (there should be none: every source is keyless)
- [ ] `nox -s audit` (pip-audit) reports no known vulnerability
- [ ] `nox -s package` passes: the wheel ships no tests and carries `Private :: Do Not Upload`

### 2.5 Persistence and recovery
- [ ] Kill the paper run mid-cycle and restart it: positions, cost basis and the audit trail continue (trading-core restores the status file; resolved markets still redeem)

### 2.6 Documentation
- [ ] `CHANGELOG.md` entry written; `docs/` pages match the code (settings, CLI, lanes)
- [ ] `AGENTS.md` Learnings Log updated for any general lesson

**Result:** PASS only when every box is ticked.

---

## 3. Capital Gate

The release gate shows the build is correct. It does not show a lane makes
money. The capital gate does that in stages, each with the least money at risk
that can still answer the question.

### 3.1 Stages (per lane)

| Stage | Money at risk | Duration | Entry condition |
|---|---|---|---|
| **0 – Backtest** | None | One collection window (≥ 4 weeks of resolved markets) | Release gate passed |
| **1 – Paper pilot** | None (paper fills on the live book) | **≥ 3 weeks** continuous, and enough closed positions for the verdict | Stage 0 GO for the lane |
| **2 – Live canary** | A dedicated wallet holding only what you can lose entirely; `max_notional` ≤ $5 | ≥ 3 weeks and ≥ 100 resolved positions | Stage 1 GO; live execution implemented and itself gated ([`LIVE-TRADING.md`](LIVE-TRADING.md)) |
| **3 – Scale-up** | At most 2× `max_notional` / exposure per step | ≥ 2 weeks per step | Stage 2 passed; previous step passed |

A release that changes a lane's money path (pricing, fees, execution,
settlement, sizing) sends **that lane** back to Stage 1 for at least one week.

### 3.2 Pre-registration (every stage)

A result is evidence only if the rule that judges it was fixed before the
data existed.

1. Before the stage starts, copy `configs/verdict/<lane>.json` (never edit it
   afterwards) and record its sha256 in the release record:
   `trading-core-audit verdict --path <any empty file> --rules configs/verdict/<lane>.json --json`
   prints it as `rules_sha256` (every later verdict prints the same value).
2. Record the module config's sha256 (`run_started` provenance does this
   automatically for paper runs) and, for the weather lane, the bias table's.
3. Judge with exactly that file. A NO-GO is a NO-GO: change the lane, then
   start a **new** stage with a new pre-registered file.

### 3.3 Stage 0 – Backtest exit criteria

Procedure: [`RESEARCH.md`](RESEARCH.md).

- [ ] The data window is recorded (dates, number of markets/events) and was **not** used to choose the lane's parameters. For the favourite lane the calibration trains on markets closing before the split and the backtest runs only on those after it
- [ ] `trading-core-audit verdict --path data/backtest/<lane>.jsonl --rules configs/verdict/<lane>.json` is **GO**
- [ ] The result survives a 1-cent wider `--half-spread` (weather: `--half-spread 0.02`; favourite: `0.015`) with net PnL still positive — paper and live fills will be worse than a mid price
- [ ] For model-based lanes (weather): the model's — or the blend's — Brier score over every priced bucket is **below the market's** in the backtest summary
- [ ] `trading-core-audit cuts` shows the lane's own metrics (`fair`, `model_p`, `sigma_c`, `calibration_n`) beat a random cut in both halves, or the lane's gate does not depend on them

A lane that fails Stage 0 does not paper trade. Fix it and re-run on a
**new** window.

**Data-limited exception.** When the free history cannot cover more than ~3
weeks (the weather lane's intraday replay needs METARs, which AWC keeps for
15 days), Stage 0 may close as **INCONCLUSIVE – PROCEED** if *both* hold:
the lane's calibration criterion (blend Brier below market Brier) passes in
both halves of the window, and the paper configuration is restricted to the
conditions where it passed. Stage 1 then carries the whole burden of proof:
its verdict must be GO **and** the intraday backtest re-run on the archive
collected during the pilot (`trading-polymarket metars`) must meet the
calibration criterion again. Record the exception in the release record.

**Sample-limited exception** (added 0.2.0 for the `fed` lane). When the
backtest already uses **all** the history that exists and still cannot
reach `min_positions` (the fed lane: 16 meetings since both venues listed
them, 23 trades), Stage 0 may close as **INCONCLUSIVE – PROCEED** only if
*every other* verdict check passes **and** the +1 c spread check passes.
Stage 1 then carries the whole burden of proof: its verdict, with the same
pre-registered rules, must be GO on its own positions (backtest positions
never count towards it). Record the exception in the release record.

**Pairs without history** (`crossvenue`). A reviewed pair has no history
until someone pairs it. Stage 0 for such a lane is a recorded dry run:
`trading-polymarket record --lane crossvenue` for ≥ 2 weeks on the approved
pairs, with no `max_edge` rejection left unexplained (a gap that large means
the pair is not the same question: remove it). Then Stage 1 as usual.

### 3.4 Stage 1 – Paper pilot exit criteria

Procedure: [`PAPER-TRADING.md`](PAPER-TRADING.md).

- [ ] ≥ 3 weeks of continuous running (restarts allowed; no gap over 6 hours) with 0 unhandled exceptions
- [ ] `trading-core-audit verdict --path data/paper/audit.jsonl --rules configs/verdict/<lane>.json --strategy <lane>` is **GO** with the pre-registered rules: enough closed positions, adjusted net above 0, both halves positive, ≥ 55% of UTC days positive, still positive without the 5 best positions, bootstrap lower bound above 0
- [ ] Paper results are not better than the Stage 0 backtest by more than its bootstrap interval (a paper run that beats its backtest by a mile usually means a fill-model bug)
- [ ] Every resolved position was redeemed at 1 or 0 and every open one belongs to an unresolved market (`trading-core-audit pnl`, `status.json`)
- [ ] The api-failure count on the dashboard stayed low and no cycle ran on stale data (event log)
- [ ] For the weather lane: the bias table was rebuilt weekly and each rebuild's sha256 recorded

### 3.5 Stage 2 – Live canary

Blocked until live execution exists. When it does:

- Configuration: start from `configs/live.example.json` (`max_notional` 5, exposure 50, one lane).
- Daily reconciliation: wallet pUSD (start, end), realized net from the audit trail, positions redeemed, fees paid; the wallet delta must match the audit within **max($1, 5%)** every day.
- Promotion to Stage 3 needs all of: ≥ 100 resolved positions; net positive after fees over the whole canary; every day reconciled; 0 positions lost from tracking; 0 duplicate or unheld sells; the breaker never overridden by hand.

### 3.6 Features that stay off until proven

| Feature / setting | Why | Condition to enable |
|---|---|---|
| `momentum.enabled` | No modelled edge; research lane | A Stage 0/1 GO on its own pre-registered rules |
| `favourite.enabled` without a calibration file | Identity calibration finds no edge (by design) | A calibration table built on a training window and a Stage 0 GO on the test window |
| `weather.market_weight` < 0.5 or `max_edge` > 0.25 | Trusts the model more than TP-1 showed was safe | Backtest and paper evidence at the new values |
| `exit_at_bid` > 0 | Sells into the book before resolution; untested economics | Paper evidence that it beats holding |
| Arbitrage execution | Multi-leg orders cannot be placed atomically through the engine | A dedicated executor, gated like live execution |
| Any paid data source (X/Twitter API, paid weather) | Not needed so far; costs must be earned first | A lane whose Stage 1 GO is shown to depend on it |

### 3.7 Stop triggers (any stage)

Stop the lane, drop it back one stage and open a `docs/dev/BUGS.md` row if:

- the daily drawdown breaker trips twice in a week;
- a position is sold twice, sold while not held, or lost from tracking;
- a resolved market is not redeemed within one cycle of Gamma showing it resolved;
- a market's resolution rules change and the lane trades it before the parser is updated;
- paper and backtest disagree by more than the bootstrap interval with no explanation;
- an unhandled exception or crash loop needs a manual restart.

---

## 4. Lane promotion summary

```text
            release gate PASS
                   │
     Stage 0  backtest  ── verdict GO on a window not used for tuning
                   │
     Stage 1  paper ≥ 3 weeks ── verdict GO with pre-registered rules
                   │
     (live execution implemented and gated — LIVE-TRADING.md)
                   │
     Stage 2  live canary ≤ $5 / trade ── ≥ 100 resolved, reconciled daily
                   │
     Stage 3  scale ×2 per step, ≥ 2 weeks per step
```

---

## 5. Release record

Keep one record per release or stage in `CHANGELOG.md` (or a linked file in
`docs/dev/releases/`). Outcomes, not terminal dumps.

```markdown
### Release record – vX.Y.Z (YYYY-MM-DD)
- Commit: <sha>; trading-core commit: <sha>
- Release gate: PASS / FAIL (failed items: …)
- Tests: <n> collected, all passed; coverage 100% on 3.11–3.14 (CI run: <link>)
- Per lane:
  - weather: stage <n>; verdict rules sha256 <hash>; bias table sha256 <hash>;
    window <dates>; GO / NO-GO (failed checks: …); net <$>; positions <n>
  - favourite: stage <n>; rules sha256 <hash>; calibration sha256 <hash>;
    train/test split <date>; GO / NO-GO …
  - fed / crossvenue: stage <n>; rules sha256 <hash>; history sha256 (fed) or
    pairs file sha256 (crossvenue); GO / NO-GO …
- Live canary daily log (stage 2+): date | wallet Δ | audit net | gap | resolved | fees
- Sign-off: <operator>
```

---

## 6. Versioning

Semantic versioning. While `0.x`, a MINOR bump may change config keys or file
formats and the changelog says so. `1.0.0` is the first release with a lane
that passed Stage 3. Tag `vX.Y.Z` on the commit that passed the release gate.
