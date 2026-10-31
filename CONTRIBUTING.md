# Contributing

trading-polymarket is a proprietary module for trading-core (see `LICENSE`).
These are the rules for changing it.

## 1. Issues

Search for an existing issue first. A new one gives the Python, trading-core
and trading-polymarket versions, the command or config that shows the
problem, what actually happened (with the full traceback or the `error:`
line), and what you expected. A problem with a venue's API names the
endpoint and the response.

## 2. Pull requests

- For anything beyond a small fix, open an issue first and discuss it.
- Work on a branch: `fix/<short-description>`, `feature/<short-description>`
  or `docs/<short-description>`; a release is `release/vX.Y.Z`. Pull requests
  from `main` are not accepted.
- New behaviour comes with tests in the mirrored layout
  ([`docs/dev/TESTING.md`](docs/dev/TESTING.md)); a bug fix comes with a
  [`docs/dev/BUGS.md`](docs/dev/BUGS.md) row and section (next free
  `TP-<n>` is in the file) and a `@pytest.mark.regression("TP-<n>")` test.
- Docs change in the same pull request as the code they describe (the
  workflow list in [`docs/dev/README.md`](docs/dev/README.md)); a new
  feature takes the next `FEAT-<n>` from trading-core's
  `docs/dev/PROPOSED-FEATURES.md`.
- CI must pass: Ruff, Black, flake8, mypy, pip-audit, the package check, and
  the tests with 100% statement and branch coverage on Python 3.11–3.14.
- Reference the issue in the description (`fixes #23`).
- If `main` moved on, **rebase**, don't merge.
- An engine change belongs in trading-core, not here.

## 3. Setup

```bash
git clone https://github.com/andy-shady-org/trading-core.git
git clone https://github.com/andy-shady-org/trading-polymarket.git
python3 -m venv .venv && source .venv/bin/activate     # Python 3.11–3.14
python -m pip install --upgrade pip
python -m pip install -e trading-core -e 'trading-polymarket[dev]'
```

## 4. Commands

```bash
nox -s lint mypy tests   # the gate (tests on every installed interpreter of 3.11–3.14)
nox -s tests-3.14        # one interpreter
nox -s tests-fast        # unit and property tests, no coverage gate
nox -s format            # ruff import order, black
nox -s audit             # pip-audit
nox -s package           # builds the wheel; checks it is private and ships no tests
```

Every session installs trading-core from `TRADING_CORE_SOURCE` (default
`../trading-core`). Ruff, Black and mypy target Python 3.11, so newer-only
syntax fails even on 3.14.

## 5. CI

`.github/workflows/tests.yml` runs on every push and pull request to `main`:
`nox -s tests-<version>` on 3.11, 3.12, 3.13 and 3.14, and
`nox -s lint mypy audit package` on 3.14. It checks out the private
trading-core with the `TRADING_CORE_TOKEN` secret
([`docs/dev/TESTING.md`](docs/dev/TESTING.md#3-ci)).

## 6. Releases

Versions follow
[`docs/dev/RELEASE-GATE.md` §6](docs/dev/RELEASE-GATE.md#6-versioning), with
no pre-releases (`rc`, `alpha`, `beta`). There is no release workflow: a
release is made by hand, in five steps.

1. **Gate and branch.** Run the release gate
   ([`docs/dev/RELEASE-GATE.md` §2](docs/dev/RELEASE-GATE.md#2-release-gate-every-release)). On a `release/vX.Y.Z` branch:
   the version in `pyproject.toml` and `trading_polymarket/__init__.py` (`__version__`),
   and the `CHANGELOG.md` entry with its release record. Open a pull request.
2. **Merge** the pull request in the GitHub UI.
3. **Sign and push the tag on the Mac.** Never create the tag in the GitHub
   UI: a tag GitHub creates (a new name typed in "Draft a new release") is
   unsigned, and every runtime refuses it.

   ```bash
   git switch main && git pull
   git tag -s v0.3.0 -m "v0.3.0"
   git tag -v v0.3.0        # Good "git" signature for andy@shady.org ...
   git push origin v0.3.0
   ```

4. **Publish the GitHub Release** (optional) in the UI: Releases → Draft a
   new release → **Choose a tag** → pick the existing `v0.3.0` (do not type a
   new name) → title `v0.3.0` → paste the notes from its `CHANGELOG.md` entry
   → Publish release. GitHub shows the tag as Verified when the signing key
   is on the account (trading-core's `SECURITY.md`, "Signed releases").
5. **Install it** in the runtime with `bin/install-release.sh`, which checks
   both tags' signatures before it builds anything.

A tagged version that needs a fix gets a new PATCH, never a re-tag. Nothing
is published to PyPI or any other package index: the code is proprietary
([`LICENSE`](LICENSE)), and a signature does not stop anyone who has a copy
from running it (trading-core's `SECURITY.md`, "Distribution").

**Protect the release tags** (once per repository): GitHub → Settings →
Rules → Rulesets → New ruleset → **New tag ruleset**; target tags matching
`v*`; turn on **Restrict updates** and **Restrict deletions**, with no bypass.
A signed tag can then never be moved or removed, from the UI or a push.
Rulesets on a private repository need a paid GitHub plan (Pro or Team).
