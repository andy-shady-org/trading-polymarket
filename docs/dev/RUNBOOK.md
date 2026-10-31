# Runbook

How a run of this module is operated: a runtime folder beside the
repositories, pinned release copies, a smoke run, then a counted paper run
(Stage 1) that lasts **at least three weeks** and is judged by a
pre-registered rule ([`RELEASE-GATE.md` §3.4](RELEASE-GATE.md#34-stage-1--paper-exit-criteria)).

Paper fills walk the live order book, pay the market's taker fee and redeem at
1 or 0 when the market resolves, so the numbers are what live trading would
have produced at those prices — minus queue position and latency, which only
the live canary can measure.

Which runs are going now: [`RELEASE-GATE.md` §1](RELEASE-GATE.md#1-current-status).

## 1. The runtime folder

Counted runs never run from the working repositories. They run from
`~/projects/git/trading/runtime-trading`, a folder beside them that holds
tagged copies of trading-core and trading-polymarket, one venv per release,
one config per run and one data folder per run:

```text
runtime-trading/
├── bin/
│   ├── install-release.sh   # bin/install-release.sh <core tag> <module tag>: clones both tags, builds the venv
│   └── run.sh               # bin/run.sh <config> <venv>: starts one run in this terminal
├── configs/                 # one config per run (pre-registered; never edited once it has run)
│   └── verdict/             # the run's copy of configs/verdict/<lane>.json
├── releases/                # trading-core and trading-polymarket at their tags (never edited)
├── venvs/                   # polymarket-<tag>/, built from those copies
├── data/                    # one folder per run: RUN.txt, status, audit, events, log
└── README.md                # the runtime's own notes
```

The scripts and the runtime's `README.md` live in runtime-trading, not in
this repository. What they do:

- **`bin/install-release.sh v0.2.2 v0.2.1`** clones trading-core `v0.2.2` and
  trading-polymarket `v0.2.1` into `releases/` (it refuses a dirty or moved
  copy) and installs them, editable, into `venvs/polymarket-v0.2.1/`, so
  every run's `run_started` record carries both commits (`git_commit`,
  `module_git`).
- **`bin/run.sh <config> polymarket-v0.2.1`** runs `trading-core run` from
  that venv in the foreground and appends the versions, commits and hashes
  it ran with to the run's `RUN.txt`. `RESUME=1` with the same command
  continues a run after a stop.

Names and folders follow trading-core's `docs/dev/DOCUMENTATION.md` §7: a
run is `<name>-<n>` (`weather-1`, `fed-1`), with its config in
`configs/<run>.json` and every file it writes in `data/<run>/`. The runs
started before 2026-10-31 keep their names: `weather-0.2.1` and `fed-0.2.1`
use `configs/paper-weather-0.2.1.json` and `configs/paper-fed-0.2.1.json`
and write to `data/pilots/weather-0.2.1/` and `data/pilots/fed-0.2.1/`
([`releases/0.2.1.md`](releases/0.2.1.md)).

`runtime/polymarket/` (third-party projects read for ideas) is a different
folder: [`../DATA-SOURCES.md` §6](../DATA-SOURCES.md#6-runtime-repositories-hints-only).

## 2. Smoke run (about 30 minutes, never counted)

Before the first counted run of a release, check that the release copy sees
live data:

```bash
cd ~/projects/git/trading/runtime-trading
bin/install-release.sh v0.2.2 v0.2.1
bin/run.sh configs/smoke-0.2.1.json polymarket-v0.2.1      # writes data/smoke/; stop with Ctrl-C
```

Healthy after half an hour: the dashboard's `api requests` keep rising and
`api failures` stay a small fraction; `polymarket data` is not degraded; the
engine is not paused on stale market data. Do the restart drill (§8) during
the smoke run. A smoke run is never judged.

## 3. A counted run

### 3.1 Before day 1

1. Release gate passed for the tag you run ([`RELEASE-GATE.md` §2](RELEASE-GATE.md#2-release-gate-every-release)).
2. The lane passed Stage 0 (backtest GO, [`../RESEARCH.md`](../RESEARCH.md)).
3. Build the weather bias table: `trading-polymarket bias --days 14`.
4. For the favourite lane: `trading-polymarket calibrate --all` (and set
   `favourite.enabled: true`, `favourite.calibration_path`).
5. Copy the config and the verdict rules; **never edit either after the
   start**. Point every file the run writes (`status_path`,
   `audit_log_path`, `event_log_path`, `log_file`) into `data/<run>/`:

   ```bash
   cd ~/projects/git/trading/runtime-trading
   cp ../trading-polymarket/configs/paper.example.json configs/weather-1.json   # then edit the four paths
   cp ../trading-polymarket/configs/verdict/weather.json configs/verdict/weather-1.json
   venvs/polymarket-v0.2.1/bin/trading-core check --config configs/weather-1.json
   ```

6. Write the top half of the run record, `docs/dev/runs/<run>.md`
   ([`runs/README.md`](runs/README.md)), and commit it before the start:
   commits (trading-polymarket and trading-core), the config's sha256, the
   verdict rules' sha256 (`trading-core-audit verdict --path <empty file>
   --rules … --json` → `rules_sha256`), the bias table's and the
   calibration's sha256.

### 3.2 Run

```bash
tmux new -s weather
cd ~/projects/git/trading/runtime-trading
bin/run.sh configs/weather-1.json polymarket-v0.2.1
```

Run it **in the foreground**, in a terminal you look at: the dashboard shows
failures as they happen and a stopped run is a stopped terminal, which a
background service hides. Use tmux (or screen) so the run outlives the
terminal window: `tmux new -s weather`, start the run, detach with
`Ctrl-b d`, re-attach with `tmux attach -t weather`. There is no automatic
restart on purpose: after a crash or reboot, read why it stopped, then start
it again with the same config (`RESUME=1 bin/run.sh …`); the status file
restores positions and the audit trail continues. A counted run allows
restarts but no gap over 6 hours
([`RELEASE-GATE.md` §3.4](RELEASE-GATE.md#34-stage-1--paper-exit-criteria)), so check the terminal daily. `SIGUSR1`
pauses and resumes entries (exits and resolutions keep running).

The weather lane reads its bias table once, at start, and uses it only
before a day's first METAR (TP-11). A run that trades only from 15:00 local
(`min_local_hour: 15`, as configured) never prices with it, so it needs no
weekly rebuild. A configuration that trades earlier does: after each weekly
`trading-polymarket bias` rebuild, restart the run (`Ctrl-C`, then the same
command) and record the new hash in the run record.

One cron job is needed, because the Aviation Weather Center keeps only
~15 days of METARs and the read-out needs the whole run:

```cron
15 0 * * *  cd ~/projects/git/trading/trading-polymarket && .venv/bin/trading-polymarket metars    # required for the weather lane
```

`metars` archives the observations the intraday backtest needs at the
read-out into `data/metars/` under the directory it runs in (here the
trading-polymarket checkout); the weather lane's Stage 1 also requires it
([`RELEASE-GATE.md` §3.3](RELEASE-GATE.md#33-stage-0--evidence-exit-criteria)).
`trading-polymarket record --cycles 288 --interval 300` and
`trading-polymarket arb` are optional research runs.

### 3.3 The fed lane: a second instance

The `fed` lane runs in its **own** trading-core process, so its breaker,
exposure and audit trail never mix with the weather run's:

```bash
cp ../trading-polymarket/configs/paper-fed.example.json configs/fed-1.json   # paths into data/fed-1/
cp ../trading-polymarket/configs/verdict/fed.json configs/verdict/fed-1.json
venvs/polymarket-v0.2.1/bin/trading-core check --config configs/fed-1.json
bin/run.sh configs/fed-1.json polymarket-v0.2.1
```

Run it like the weather run, in its own terminal or tmux window. It needs no
cron job. Expect few trades: a signal needs Polymarket at least
2 c below Kalshi's mid with a tight, traded Kalshi quote, and most hours
the venues sit within a cent. Positions are sold by the module when
Polymarket's bid reaches Kalshi's mid (exit reason `converged`) or redeemed
at resolution. Judge it with
`trading-core-audit verdict --path data/fed-1/audit.jsonl --rules configs/verdict/fed-1.json --strategy fed`.

## 4. Daily check (5 minutes)

| Look at | Where | Healthy |
|---|---|---|
| Engine alive, last cycle recent | dashboard / `data/<run>/status.json` | cycle < 2 × `cycle_seconds` ago |
| API health | dashboard rows `api requests`, `api failures`, `last api error` | failures a small fraction; no error repeating for hours |
| Positions | dashboard | every open position belongs to an unresolved market; prices shown in cents |
| Yesterday's PnL by lane | `trading-core-audit pnl --path data/<run>/audit.jsonl --group-by strategy` | — (informational until the verdict) |
| Resolutions | `trading-core-audit pnl --path data/<run>/audit.jsonl --group-by reason` | `resolved` sells at 1.0 or 0.0 only |
| Breaker | dashboard / alerts | not tripped; if tripped, read the event log before resuming |

Weekly, only when the weather lane trades before 15:00 local (§3.2): rebuild
the bias table (`trading-polymarket bias`), record its sha256 and restart the
run so the lane loads it.

## 5. Things that are normal

- **No trades for hours.** The weather lane needs a mispricing larger than
  `min_edge` after blending with the market; most of the time there is none.
  Once it holds `max_positions_per_day` (3) positions closing on one date it
  takes no more for that date: the event log shows `lane-day-cap` rejections.
- **Positions marked stale near resolution.** The CLOB removes a market's book
  when it closes; until Gamma shows the result the quote is stale and the
  position is held. It is redeemed in the first cycle after resolution.
- **"Disagreements" in the weather scout.** Buckets where the model and the
  market differ by more than `max_edge` are deliberately skipped (TP-1).

## 6. Incidents: things that are not normal

See [`RELEASE-GATE.md` §3.7](RELEASE-GATE.md#37-stop-triggers-any-stage). In short:
a breaker trip twice in a week, a position sold twice or unredeemed after
resolution, repeated crashes, or a market whose resolution rules changed
being traded. Stop the lane (set `enabled: false` and restart), open a
`docs/dev/BUGS.md` row, fix, and start a **new** run with the next number
(`weather-2`).

## 7. Read-out (after ≥ 3 weeks)

```bash
trading-polymarket weather-history --start <run start> --end <run end>
trading-polymarket backtest weather --intraday --entry-hour 15 \
    --metar-archive ~/projects/git/trading/trading-polymarket/data/metars   # Brier must favour the blend
trading-core-audit verdict --path data/weather-1/audit.jsonl \
    --rules configs/verdict/weather-1.json --strategy weather
trading-core-audit cuts --path data/weather-1/audit.jsonl --strategy weather \
    --keep 'fair>=0.5' --keep 'sigma_c<=1.5'
```

Write the outcome — GO, NO-GO or INCONCLUSIVE, the failed checks, net,
positions, days — into the run record's read-out and at the top of
[`RESULTS.md`](RESULTS.md), and update [`RELEASE-GATE.md` §1](RELEASE-GATE.md#1-current-status).
A NO-GO means the lane does not advance; change it and start a new
Stage 0 → Stage 1 cycle with new pre-registered rules. The 0.2.1 runs are
read out in [`releases/0.2.1.md`](releases/0.2.1.md#read-out).

## 8. Drills

**Kill and restart** (release gate §2.5), once per release, during the smoke
run: press `Ctrl-C` in the middle of a cycle, then start the same command
again with `RESUME=1`. Positions, their cost basis and the audit trail must
continue; a market that resolved meanwhile must still redeem. Record the
result in the release record.
