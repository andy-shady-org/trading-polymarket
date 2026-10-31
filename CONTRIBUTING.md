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

A release passes the release gate
([`docs/dev/RELEASE-GATE.md` §2](docs/dev/RELEASE-GATE.md#2-release-gate-every-release))
and follows its versioning policy
([§6](docs/dev/RELEASE-GATE.md#6-versioning)):

1. On `release/vX.Y.Z`: bump the version in `pyproject.toml` and
   `trading_polymarket/__init__.py`, write the `CHANGELOG.md` entry and its
   release record; merge by pull request.
2. Tag the merge commit on `main`, annotated and private, and push the tag:

   ```bash
   git tag -a v0.2.2 -m "v0.2.2"
   git push origin v0.2.2
   ```

There are no pre-releases (`rc`, `alpha`, `beta`): a tagged version that
needs a fix gets a new PATCH, never a re-tag. Nothing is published to PyPI
or any other index, and no GitHub Release is created.
