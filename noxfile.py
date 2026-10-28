"""Quality gates for trading-polymarket (docs/dev/TESTING.md).

Tests run on every supported interpreter (``requires-python = ">=3.11"``);
tooling sessions run once, on the newest. trading-core is private, so every
session installs it first from ``TRADING_CORE_SOURCE``: a local checkout path
(default ``../trading-core``) or any pip requirement such as
``git+ssh://git@github.com/andy-shady-org/trading-core.git@main``.
"""

import os
import zipfile
from pathlib import Path

import nox

PYTHON_VERSIONS = ["3.11", "3.12", "3.13", "3.14"]
TOOLING_PYTHON = "3.14"
nox.options.sessions = ["lint", "mypy", "tests"]


def _install(session):
    source = os.environ.get("TRADING_CORE_SOURCE", "../trading-core")
    if Path(source).is_dir():
        session.install(str(Path(source).resolve()))
    else:
        session.install(source)
    session.install("-e", ".[dev]")


@nox.session(python=PYTHON_VERSIONS)
def tests(session):
    """Full suite with the 100% statement and branch coverage gate."""
    _install(session)
    session.run(
        "pytest",
        "-q",
        "--cov=trading_polymarket",
        "--cov-report=term-missing",
        "--cov-report=xml",
        "--cov-fail-under=100",
        *session.posargs,
    )


@nox.session(name="tests-fast", python=PYTHON_VERSIONS, default=False)
def tests_fast(session):
    _install(session)
    session.run("pytest", "-q", "-m", "not slow and not integration", *session.posargs)


@nox.session(python=[TOOLING_PYTHON])
def lint(session):
    _install(session)
    session.run("ruff", "check", ".")
    session.run("black", "--check", ".")
    session.run("flake8", ".")


@nox.session(python=[TOOLING_PYTHON])
def mypy(session):
    _install(session)
    session.run("mypy")


@nox.session(python=[TOOLING_PYTHON], default=False)
def format(session):
    _install(session)
    session.run("ruff", "check", "--select", "I", "--fix", ".")
    session.run("black", ".")


@nox.session(python=[TOOLING_PYTHON], default=False)
def audit(session):
    _install(session)
    # trading-core is a private, locally installed package: pip-audit cannot
    # look it up on PyPI, so it is skipped by name.
    session.run("pip-audit", "--skip-editable")


@nox.session(python=[TOOLING_PYTHON], default=False)
def package(session):
    """Build the wheel and check it is private and ships no tests."""
    session.install("build")
    out_dir = Path(session.create_tmp()) / "dist"
    for stale in out_dir.glob("*"):
        stale.unlink()
    session.run("python", "-m", "build", "--outdir", str(out_dir))
    wheels = sorted(out_dir.glob("*.whl"))
    if len(wheels) != 1:
        session.error(f"expected one wheel in {out_dir}, found {len(wheels)}")
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        metadata_name = next(n for n in names if n.endswith(".dist-info/METADATA"))
        metadata = wheel.read(metadata_name).decode("utf-8")
    leaked = [n for n in names if n.startswith("trading_polymarket/tests/")]
    if leaked:
        session.error(f"wheel ships {len(leaked)} test files, e.g. {leaked[0]}")
    if "Classifier: Private :: Do Not Upload" not in metadata:
        session.error("wheel metadata lacks the 'Private :: Do Not Upload' classifier")
    session.log(f"{wheels[0].name}: {len(names)} files, no tests, private")
