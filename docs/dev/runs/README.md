# Run records

One file per counted run, `docs/dev/runs/<run>.md`, as trading-core's
`docs/dev/DOCUMENTATION.md` §7 and §8.2 define them. Which runs are going
now: [`../RELEASE-GATE.md` §1](../RELEASE-GATE.md#1-current-status). How a run
is operated: [`../RUNBOOK.md`](../RUNBOOK.md).

## 1. Names

A run is `<name>-<n>`: `weather-1`, `fed-1`, then `weather-2`, … `<name>` says
what the run is for (here, the lane it judges); `<n>` counts up per name and
is never reused, even for a run that was stopped early. Its config is
`configs/<run>.json` and every file it writes is in `data/<run>/`, both in
runtime-trading.

## 2. Runs before the standard

Counted runs started before 2026-10-31 have no file here. Their
pre-registration (code, config and rules hashes) and their read-out are in
their release record, and they keep the names they were given:

| Run | Lane | Release | Record |
|---|---|---|---|
| (unnamed; `data/paper/`) | weather | 0.1.0 | [`../releases/0.1.0-weather-stage1.md`](../releases/0.1.0-weather-stage1.md) |
| `weather-0.2.0` | weather | 0.2.0 | [`../releases/0.2.0.md`](../releases/0.2.0.md) |
| `fed-0.2.0` | fed | 0.2.0 | [`../releases/0.2.0.md`](../releases/0.2.0.md) |
| `weather-0.2.1` | weather | 0.2.1 | [`../releases/0.2.1.md`](../releases/0.2.1.md) |
| `fed-0.2.1` | fed | 0.2.1 | [`../releases/0.2.1.md`](../releases/0.2.1.md) |

The next counted runs are `weather-1` and `fed-1`.

## 3. The template

The top half is written and committed **before the run starts** and is
never edited after; the read-out is added when the run ends. A correction is
a new dated line, not an edit.

```markdown
# Run weather-1

## Pre-registration (written YYYY-MM-DD HH:MM UTC, before the start)
- Question: what the run decides, in one sentence
- Code: trading-core vA.B.C (<commit>), trading-polymarket vX.Y.Z (<commit>)
- Config: configs/weather-1.json, sha256 <hash>
- Verdict rules: configs/verdict/weather-1.json, sha256 <hash> (rules_sha256 <hash>), with the rule in words
- Lane inputs: bias table sha256 <hash> (weather, when it prices entries); calibration sha256 (favourite); pairs file sha256 (crossvenue)
- Started: <UTC>; planned end: <UTC>, or the position count the verdict needs
- Stage: the stage each lane is at, and what GO and NO-GO lead to

## Read-out (added at the end)
- Ran: <UTC> to <UTC>; gaps: none, or what and why
- Per lane: positions, net, win rate, verdict (GO / NO-GO / INCONCLUSIVE) and the checks that failed
- What it means, and what happens next
```

The read-out also goes at the top of [`../RESULTS.md`](../RESULTS.md).
