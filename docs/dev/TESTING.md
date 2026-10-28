# Testing

## The gate

```bash
nox -s lint mypy tests          # trading-core comes from ../trading-core by default
```

| Session | Runs | Must |
|---|---|---|
| `lint` (3.14) | `ruff check .`, `black --check .`, `flake8 .` | pass |
| `mypy` (3.14, checks as 3.11) | `mypy` (package and tests, against trading-core's types) | no issues |
| `tests-3.11` … `tests-3.14` | `pytest --cov=trading_polymarket --cov-fail-under=100` | pass with 100% **statement and branch** coverage on every version |
| `tests-fast` | unit and property tests, no coverage | quick loop |
| `format` | `ruff --select I --fix`, `black` | — |
| `audit` | `pip-audit --skip-editable` | no known vulnerability |
| `package` | build; the wheel ships no tests and is `Private :: Do Not Upload` | — |

Every session first installs trading-core from `TRADING_CORE_SOURCE`: a
checkout path (default `../trading-core`) or any pip requirement, e.g.
`TRADING_CORE_SOURCE=git+ssh://git@github.com/andy-shady-org/trading-core.git@main nox -s tests`.

The suite (300+ tests) runs in a few seconds and **never touches the
network**: `tests/conftest.py` blocks DNS for the whole session and every
HTTP call goes through `FakeTransport`. Python 3.11's coverage tracer can miss
a `continue` right after an `await`; prefer code that does not need one (see
`research/arb.py`) over pragmas.

## CI

`.github/workflows/tests.yml` checks out this repository **and** the private
`andy-shady-org/trading-core` side by side and runs nox with
`TRADING_CORE_SOURCE` pointing at the checkout. It needs one repository
secret:

- **`TRADING_CORE_TOKEN`**: a fine-grained personal access token with
  *Contents: read* on `andy-shady-org/trading-core` (Settings → Developer
  settings → Fine-grained tokens), stored under this repository's Settings →
  Secrets and variables → Actions.

`TRADING_CORE_REF` (workflow env, default `main`) picks the trading-core
branch or tag to test against; pin it to a tag for releases.

## Layout

```text
trading_polymarket/tests/
├── conftest.py          markers by directory + environment isolation, nothing else
├── fixtures/            small real API payloads recorded on 2026-10-28
│                        (weather_event, book, resolved_market, prices_history, metar)
├── support/
│   ├── constants.py     NOW, YES, NO, CONDITION
│   ├── factories.py     gamma_market, market, resolved, book_payload, book,
│   │                    weather_event, forecast_payload, metar_row, history_row
│   └── fakes.py         FakeTransport (URL-substring routes, Sequenced replies),
│                        fake_http, RecordingHost, Clock
├── unit/                one file per source module (clients/, strategies/, research/ mirrored)
├── integration/
│   ├── test_paper_run.py        trading-core's engine + this module: buy, resolve, redeem; audit = engine
│   └── test_module_plugin.py    entry point, every config builds, trading-core-audit reads backtests
└── property/
    └── test_pricing_properties.py   fees, book walks, bucket partition, calibration bounds
```

`unit/test_suite_layout.py` enforces: a mirrored test for every source
module, only `conftest.py`/`__init__.py` in the tests root, an `__init__.py`
in every test directory, no coverage-named files, regression tags that match
`docs/dev/BUGS.md` both ways, and that every file parses as Python 3.11.
`unit/test_config.py` fails when a settings key is missing from
`docs/CONFIGURATION.md`.

## Markers

| Marker | Applied |
|---|---|
| `unit`, `integration`, `property` | automatically, by directory |
| `regression("TP-<n>")` | on the test that guards a fixed bug |
| `slow` | tests that need real waiting (none today) |

## Writing tests

- Build payloads with `factories.py`; route them with `FakeTransport({"/book": payload})`.
  A route value may be a payload, a `Response`, an exception (raised), a
  callable taking the URL, or `Sequenced(a, b, …)` for successive replies.
- Inject time with `Clock(NOW)`; `NOW` is 2026-10-28 12:00 UTC (07:00 in
  Dallas, the default weather station).
- A bug fix gets a `BUGS.md` row and `@pytest.mark.regression("TP-<n>")`.
