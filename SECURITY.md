# Security policy

## 1. Supported versions

| Version | Supported |
|---|---|
| 0.2.x (latest: 0.2.1) | yes |
| 0.1.x | no |

## 2. Reporting a vulnerability

Do not report security problems in a public GitHub issue. Contact the owner
directly through GitHub.

## 3. Handling secrets

- **There are none today.** Every data source is free and keyless, and the
  module reads no environment variable ([`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md)).
  Live execution, which would need a key, is not built and refuses every
  order ([`docs/LIVE-TRADING.md`](docs/LIVE-TRADING.md)).
- **When live trading is built**, the wallet key and the CLOB API credentials
  come from `TRADING_PM_*` environment variables only, never from settings:
  trading-core hashes the settings file into every run's provenance.
- **Redaction**: everything trading-core writes to logs, events, status
  files and alerts passes its redaction. The module registers Polymarket's
  public ids (token ids of 20 digits or more, `0x` condition ids) as public
  (`is_public_identifier`), so only key-like strings are masked.
- **Local files**: `configs/*.json` (except the examples), `.envrc` and
  `data/` are git-ignored, so an operator's copies never get committed.
- **Tests** remove every `TRADING_CORE_*` and `TRADING_PM_*` variable before
  each test and block DNS for the whole session, so no test can reach the
  network or read a real credential.
- **CI** needs two repository secrets: `TRADING_CORE_TOKEN` (a fine-grained
  token with read-only *Contents* access to the private trading-core) and
  `CODECOV_TOKEN` (coverage upload) ([`docs/dev/TESTING.md`](docs/dev/TESTING.md#3-ci)).
- **Dependencies**: `nox -s audit` (pip-audit) is part of the release gate.

## Signed releases

Every release tag of this repository, from `v0.3.0` on, is signed with the
operator's SSH key (`git tag -s`), made on the operator's Mac and never in
the GitHub web UI. Each runtime's `bin/install-release.sh` refuses a tag
whose signature does not verify against its `allowed_signers`, and
trading-core (0.3.0 and later) refuses to start a live run on a module
checkout that is not a clean, signed release tag. Setup, the release steps
and what to do if the key is lost: trading-core's `SECURITY.md`, "Signed
releases"; this repository's steps: [`CONTRIBUTING.md`](CONTRIBUTING.md#6-releases).

Tags made before signing (`v0.1.0` to `v0.2.1`) are not signed; installing one again
needs `ALLOW_UNSIGNED=1`, and a live run on it is refused.

