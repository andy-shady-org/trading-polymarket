# Developer documentation

For maintainers of trading-polymarket. The operator's pages start at
[`../USER-GUIDE.md`](../USER-GUIDE.md); the engine's are in trading-core.

Every page follows trading-core's `docs/dev/DOCUMENTATION.md` (the
documentation standard): its layout, writing style, words, versioning,
capital stages, run names, records, IDs and history rules. When a page here
and the standard disagree, the standard wins and the page is fixed.

## 1. Pages

| Page | What it holds |
|---|---|
| [`RELEASE-GATE.md`](RELEASE-GATE.md) | §1 current status (the only place it lives), §2 release gate, §3 capital gate and stages, §4 this repository's gates, §5 release record template, §6 versioning |
| [`RUNBOOK.md`](RUNBOOK.md) | Operating a run: the runtime-trading folder, the smoke run, a counted run, the daily check, incidents, the read-out, drills |
| [`RESULTS.md`](RESULTS.md) | The results log: every study, backtest and run, with its verdict (newest first) |
| [`TODO.md`](TODO.md) | Open work only: Now / Next / Later, then by subject |
| [`DONE.md`](DONE.md) | Finished work from 2026-10-31, under its `TODO.md` heading, with its release |
| [`BUGS.md`](BUGS.md) | Every bug (`TP-<n>`): a status table, then cause, fix and test |
| [`PROPOSED-FEATURES.md`](PROPOSED-FEATURES.md) | Features not built (FEAT IDs from trading-core's series) |
| [`TESTING.md`](TESTING.md) | The `nox` gate, CI, the test layout, isolation, markers, conventions |
| [`ARCHITECTURE-DECISIONS.md`](ARCHITECTURE-DECISIONS.md) | Decisions and why, as `ADR-NNN` |
| [`COSTS.md`](COSTS.md) | What this module pays: nothing, and why (development costs are trading-core's) |
| [`releases/`](releases/) | Release records too long for `CHANGELOG.md` (0.1.0, 0.2.0, 0.2.1), with the pre-registration of the runs before 2026-10-31 |
| [`runs/`](runs/README.md) | One record per counted run from 2026-10-31 (`weather-1.md`, `fed-1.md`, …) |

Root files: [`CONTRIBUTING.md`](../../CONTRIBUTING.md) (branches, pull
requests, the gate, tagging), [`SECURITY.md`](../../SECURITY.md),
[`AGENTS.md`](../../AGENTS.md) (rules and learnings for coding agents),
[`CHANGELOG.md`](../../CHANGELOG.md).

## 2. Workflow

```bash
cd ~/projects/git/trading
python3 -m venv .venv && source .venv/bin/activate     # Python 3.11–3.14
pip install -e trading-core
pip install -e "trading-polymarket[dev]"
cd trading-polymarket && nox -s lint mypy tests
```

- One branch per change (`fix/…`, `feature/…`, `docs/…`; `release/vX.Y.Z`
  for a release).
- A bug fix gets a `BUGS.md` row and section (next free `TP-<n>` is in the
  file), a `@pytest.mark.regression("TP-<n>")` test and, when the lesson is
  general, a Learnings Log entry in [`AGENTS.md`](../../AGENTS.md).
- Coverage stays at 100% on 3.11–3.14; `fail_under` is never lowered.
- Docs move with the code, in the same change: settings in
  `docs/CONFIGURATION.md` (a test checks it), variables in
  `docs/ENVIRONMENT.md`, commands in `docs/CLI.md`, built features in
  `docs/FEATURES.md`, unbuilt ones in `PROPOSED-FEATURES.md`, results in
  `RESULTS.md`, status in `RELEASE-GATE.md` §1, open work in `TODO.md`,
  finished work in `DONE.md`, every release in `CHANGELOG.md`.
- An engine change goes to trading-core, with its own tests and bug ID
  (`TC-<n>`); this repository then needs the trading-core version that has
  it (`pyproject.toml`).
