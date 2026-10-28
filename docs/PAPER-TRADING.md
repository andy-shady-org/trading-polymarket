# Paper trading runbook (Stage 1)

The paper pilot runs the real engine on live Polymarket data for **at least
three weeks** and then lets a pre-registered rule decide whether a lane goes
further ([`GO-NO-GO.md` §3.4](GO-NO-GO.md#34-stage-1--paper-pilot-exit-criteria)).
Paper fills walk the live order book, pay the market's taker fee and redeem at
1 or 0 when the market resolves, so the numbers are what live trading would
have produced at those prices — minus queue position and latency, which only
the live canary can measure.

## 1. Before day 1

1. Release gate passed for the commit you run ([`GO-NO-GO.md` §2](GO-NO-GO.md#2-release-gate-every-release)).
2. The lane passed Stage 0 (backtest GO, [`RESEARCH.md`](RESEARCH.md)).
3. Build the weather bias table: `trading-polymarket bias --days 14`.
4. For the favourite lane: `trading-polymarket calibrate --all` (and set
   `favourite.enabled: true`, `favourite.calibration_path`).
5. Copy the config and the verdict rules; **never edit either after the
   start**:

   ```bash
   cp configs/paper.example.json configs/paper.json
   cp configs/verdict/weather.json configs/verdict/weather.pilot.json
   trading-core check --config configs/paper.json
   ```

6. Record in the release record: commit (trading-polymarket and
   trading-core), `configs/paper.json` sha256, verdict rules sha256
   (`trading-core-audit verdict --path <empty file> --rules … --json` →
   `rules_sha256`), bias table and calibration sha256.

## 2. Run

```bash
trading-core run --config configs/paper.json              # dashboard
trading-core run --config configs/paper.json --headless   # server / tmux
```

Run it under a supervisor (systemd, launchd or tmux + a restart loop; trading-core's `docs/OPERATIONS.md`) so it restarts
after a crash or reboot; the status file restores positions and the audit
trail continues. `SIGUSR1` pauses and resumes entries (exits and resolutions
keep running).

Alongside, from cron:

```cron
15 0 * * *  cd ~/projects/git/trading/trading-polymarket && .venv/bin/trading-polymarket metars    # required for the weather lane
0 * * * *   cd ~/projects/git/trading/trading-polymarket && .venv/bin/trading-polymarket arb       # optional
```

`metars` archives the observations the intraday backtest needs at the
read-out (the weather lane's Stage 1 also requires it, [`GO-NO-GO.md` §3.3](GO-NO-GO.md#33-stage-0--backtest-exit-criteria)).
`trading-polymarket record --cycles 288 --interval 300` (daily) is optional.

## 3. Daily check (5 minutes)

| Look at | Where | Healthy |
|---|---|---|
| Engine alive, last cycle recent | dashboard / `data/paper/status.json` | cycle < 2 × `cycle_seconds` ago |
| API health | dashboard rows `api requests`, `api failures`, `last api error` | failures a small fraction; no error repeating for hours |
| Positions | dashboard | every open position belongs to an unresolved market; prices shown in cents |
| Yesterday's PnL by lane | `trading-core-audit pnl --path data/paper/audit.jsonl --group-by strategy` | — (informational until the verdict) |
| Resolutions | `trading-core-audit pnl --group-by reason` | `resolved` sells at 1.0 or 0.0 only |
| Breaker | dashboard / alerts | not tripped; if tripped, read the event log before resuming |

Weekly: rebuild the bias table (`trading-polymarket bias`), record its sha256
and restart the run so the lane loads it.

## 4. Things that are normal

- **No trades for hours.** The weather lane needs a mispricing larger than
  `min_edge` after blending with the market; most of the time there is none.
- **Positions marked stale near resolution.** The CLOB removes a market's book
  when it closes; until Gamma shows the result the quote is stale and the
  position is held. It is redeemed in the first cycle after resolution.
- **"Disagreements" in the weather scout.** Buckets where the model and the
  market differ by more than `max_edge` are deliberately skipped (TP-1).

## 5. Things that are not normal (stop triggers)

See [`GO-NO-GO.md` §3.7](GO-NO-GO.md#37-stop-triggers-any-stage). In short:
a breaker trip twice in a week, a position sold twice or unredeemed after
resolution, repeated crashes, or a market whose resolution rules changed
being traded. Stop the lane (set `enabled: false` and restart), open a
`docs/dev/BUGS.md` row, fix, and start a **new** pilot.

## 6. Read-out (after ≥ 3 weeks)

```bash
trading-polymarket weather-history --start <pilot start> --end <pilot end>
trading-polymarket backtest weather --intraday --entry-hour 15   # archive merged in; Brier must favour the blend
for lane in weather favourite; do
  trading-core-audit verdict --path data/paper/audit.jsonl \
      --rules configs/verdict/$lane.pilot.json --strategy $lane
done
trading-core-audit cuts --path data/paper/audit.jsonl --strategy weather \
    --keep 'fair>=0.5' --keep 'sigma_c<=1.5'
```

Write the outcome — GO or NO-GO, the failed checks, net, positions, days —
into the release record and `docs/RESEARCH.md`'s results log. A NO-GO means
the lane does not advance; change it and start a new Stage 0 → Stage 1 cycle
with new pre-registered rules.
