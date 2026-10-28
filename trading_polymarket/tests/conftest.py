"""Global pytest fixtures: layer markers and environment isolation only.

Shared builders live in ``tests/support/`` (factories, fakes, constants);
see docs/dev/TESTING.md.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from trading_core.module import registry
from trading_core.ops import redact

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", ""})
_TESTS_ROOT = Path(__file__).parent
# HTTP clients send requests for any host to a configured proxy, which is a
# local address, so the DNS guard never sees the real host (pumpfun BUG-143).
_PROXY_ENV = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_SESSION_GETADDRINFO: dict[str, Any] = {}


def _layer_marker(path: Path) -> str:
    """``integration`` / ``property`` by directory; everything else ``unit``."""
    try:
        parts = path.relative_to(_TESTS_ROOT).parts
    except ValueError:
        return "unit"
    if parts and parts[0] in ("integration", "property"):
        return parts[0]
    return "unit"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(_layer_marker(Path(item.path)))


def _guard_getaddrinfo(real_getaddrinfo: Any) -> Any:
    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        name = host.decode() if isinstance(host, bytes) else str(host or "")
        if name not in _LOCAL_HOSTS:
            raise socket.gaierror(f"external network disabled in tests: {name}")
        return real_getaddrinfo(host, *args, **kwargs)

    return guarded_getaddrinfo


def pytest_configure(config: pytest.Config) -> None:
    """Block DNS for the whole session, threads included (pumpfun BUG-143)."""
    _SESSION_GETADDRINFO["real"] = socket.getaddrinfo
    socket.getaddrinfo = _guard_getaddrinfo(socket.getaddrinfo)


def pytest_unconfigure(config: pytest.Config) -> None:
    real = _SESSION_GETADDRINFO.pop("real", None)
    if real is not None:
        socket.getaddrinfo = real


@pytest.fixture(autouse=True)
def isolate_test_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    """Fresh working directory, no proxy, no ambient ``TRADING_CORE_*`` settings.

    Every file a test writes through a default path (``data/history/...``,
    ``data/calibration.json``) lands in ``tmp_path``. The DNS guard keeps
    every test off the network: HTTP goes through fake transports. In-process module and
    public-identifier registrations are undone after each test.
    """
    for name in _PROXY_ENV:
        monkeypatch.delenv(name, raising=False)
    for name in [
        key for key in os.environ if key.startswith(("TRADING_CORE_", "TRADING_PM_"))
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    registered = dict(registry._REGISTERED)
    identifiers = list(redact._PUBLIC_IDENTIFIERS)
    yield
    registry._REGISTERED.clear()
    registry._REGISTERED.update(registered)
    redact._PUBLIC_IDENTIFIERS[:] = identifiers
