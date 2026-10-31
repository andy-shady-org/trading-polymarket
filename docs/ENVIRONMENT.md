# Environment variables

**trading-polymarket reads no environment variable.** No module code under
`trading_polymarket/` calls `os.environ` or `os.getenv`: every data source is
free and keyless ([`DATA-SOURCES.md`](DATA-SOURCES.md)), so there is no key to
pass, and every choice is a `module_settings` key ([`CONFIGURATION.md`](CONFIGURATION.md)).

The engine's variables (`TRADING_CORE_ALERT_*`, `TRADING_CORE_*_PATH`,
`TRADING_CORE_GIT_COMMIT`, …) are trading-core's: see its
`docs/ENVIRONMENT.md`.

## 1. Read by the module

None.

## 2. Read by the development tools

These are read by the test and CI tooling, never by a run:

| Variable | Read by | Used for | Default |
|---|---|---|---|
| `TRADING_CORE_SOURCE` | `noxfile.py` | Where every nox session installs trading-core from: a checkout path or any pip requirement (`git+ssh://git@github.com/andy-shady-org/trading-core.git@main`) | `../trading-core` |
| `TRADING_CORE_REF` | `.github/workflows/tests.yml` (workflow `env`) | The trading-core branch or tag CI checks out | `main` |

CI also uses two repository secrets, which are not environment variables of
a run: `TRADING_CORE_TOKEN` (read access to the private trading-core) and
`CODECOV_TOKEN` (coverage upload) ([`dev/TESTING.md`](dev/TESTING.md#ci)).

The test suite removes every `TRADING_CORE_*` and `TRADING_PM_*` variable
(and the proxy variables) before each test, so nothing set in your shell can
change a result (`trading_polymarket/tests/conftest.py`).

## 3. Planned for live trading (not read yet)

Live execution is not built ([`LIVE-TRADING.md`](LIVE-TRADING.md)). When it
is, its credentials will come from environment variables with the
`TRADING_PM_` prefix, never from a settings file:

| Variable | Will hold |
|---|---|
| `TRADING_PM_PRIVATE_KEY` | The wallet's private key, which signs live orders |
| `TRADING_PM_API_KEY`, … | The CLOB API credentials (the full list is fixed when the live executor is written) |

> [!CAUTION]
> Never put a key in a settings file: trading-core hashes the settings file
> into every run's provenance (`run_started`), so a key there would be
> copied into the audit trail. Keys belong in the environment only, and every
> string written to a log, event or status file passes trading-core's
> redaction.

When the live executor reads a variable, it is added to section 1 in the
same change.

## 4. No longer read

None: no version of this module has read an environment variable.
