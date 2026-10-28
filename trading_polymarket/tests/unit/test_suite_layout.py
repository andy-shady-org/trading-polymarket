"""Guards for the test-suite layout and regression tagging (docs/dev/TESTING.md).

These tests read the source tree, the tests tree and ``docs/dev/BUGS.md``
statically, so they work the same for any pytest selection.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = TESTS_ROOT.parent
BUGS_MD = PACKAGE_ROOT.parent / "docs" / "dev" / "BUGS.md"

# Resolved bugs with no tagged test yet. This list may only shrink: tag a
# test (or add one) and remove the ID here. Reasons are kept next to each ID.
KNOWN_UNTAGGED: dict[str, str] = {}

COVERAGE_NAMED = re.compile(r"^test_(coverage_.*|.*boost.*|.*_full)\.py$")
STATUS_ROW = re.compile(
    r"^\| \*\*(TP-\d+)\*\* \|[^|]*\|[^|]*\| \*\*([A-Z ]+)\*\*", re.M
)


def _source_modules() -> list[Path]:
    """Every source module: ``<pkg>/<module>.py`` and top-level ``<module>.py``."""
    nested = [
        path
        for path in PACKAGE_ROOT.glob("*/*.py")
        if path.name != "__init__.py" and path.parent.name not in ("tests", "data")
    ]
    top = [path for path in PACKAGE_ROOT.glob("*.py") if path.name != "__init__.py"]
    return sorted(nested + top)


def _mirror(module: Path) -> Path:
    if module.parent == PACKAGE_ROOT:
        return TESTS_ROOT / "unit" / f"test_{module.name}"
    return TESTS_ROOT / "unit" / module.parent.name / f"test_{module.name}"


def _test_files() -> list[Path]:
    return sorted(TESTS_ROOT.rglob("test_*.py"))


def _regression_tags() -> set[str]:
    tags: set[str] = set()
    for path in _test_files():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith(
                "mark.regression"
            ):
                tags.update(
                    arg.value
                    for arg in node.args
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                )
    return tags


def _bug_statuses() -> dict[str, str]:
    return dict(STATUS_ROW.findall(BUGS_MD.read_text()))


@pytest.mark.parametrize(
    "module",
    _source_modules(),
    ids=lambda p: p.name if p.parent == PACKAGE_ROOT else f"{p.parent.name}/{p.name}",
)
def test_layout_every_source_module_has_mirrored_unit_test(module: Path) -> None:
    mirror = _mirror(module)
    assert mirror.is_file(), f"missing {mirror.relative_to(TESTS_ROOT)}"


def test_layout_tests_root_holds_only_conftest() -> None:
    allowed = {"conftest.py", "__init__.py"}
    stray = sorted(p.name for p in TESTS_ROOT.glob("*.py") if p.name not in allowed)
    assert stray == []


def test_layout_every_test_package_is_importable_package() -> None:
    missing = [
        d.relative_to(TESTS_ROOT).as_posix()
        for d in TESTS_ROOT.rglob("*")
        if d.is_dir() and d.name != "__pycache__" and not (d / "__init__.py").exists()
    ]
    assert missing == []


def test_layout_no_coverage_named_test_files() -> None:
    offenders = [
        p.relative_to(TESTS_ROOT).as_posix()
        for p in _test_files()
        if COVERAGE_NAMED.match(p.name)
    ]
    assert offenders == []


def test_regression_every_resolved_bug_has_a_tagged_test() -> None:
    statuses = _bug_statuses()
    resolved = {bug for bug, status in statuses.items() if status == "RESOLVED"}
    untagged = resolved - _regression_tags()
    assert sorted(untagged - set(KNOWN_UNTAGGED)) == []


def test_regression_known_untagged_list_only_shrinks() -> None:
    tags = _regression_tags()
    statuses = _bug_statuses()
    stale = sorted(
        bug for bug in KNOWN_UNTAGGED if bug in tags or statuses.get(bug) != "RESOLVED"
    )
    assert stale == [], "remove these from KNOWN_UNTAGGED"


def _oldest_supported_python() -> tuple[int, int]:
    pyproject = (PACKAGE_ROOT.parent / "pyproject.toml").read_text()
    match = re.search(r'requires-python = ">=(\d+)\.(\d+)"', pyproject)
    assert match, "requires-python must be a >=X.Y floor"
    return int(match.group(1)), int(match.group(2))


def test_source_parses_on_the_oldest_supported_python() -> None:
    floor = _oldest_supported_python()
    failures = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        try:
            ast.parse(path.read_text(), filename=str(path), feature_version=floor)
        except SyntaxError as exc:
            failures.append(f"{path.relative_to(PACKAGE_ROOT)}:{exc.lineno}: {exc.msg}")
    assert failures == []


def test_regression_tags_name_real_bugs() -> None:
    unknown = sorted(_regression_tags() - set(_bug_statuses()))
    assert unknown == []
