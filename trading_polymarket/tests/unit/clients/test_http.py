from __future__ import annotations

import io
import urllib.error
import urllib.request
from collections.abc import Mapping

import pytest

from trading_polymarket.clients import http as http_mod
from trading_polymarket.clients.http import (
    HttpError,
    JsonHttp,
    Response,
    build_url,
    urllib_transport,
)
from trading_polymarket.tests.support.fakes import (
    Clock,
    FakeTransport,
    Sequenced,
    fake_http,
)


def test_build_url_drops_none_and_encodes_bools_and_lists() -> None:
    url = build_url(
        "https://x.test/", "/p", {"a": None, "b": True, "c": False, "d": [1, 2]}
    )
    assert url == "https://x.test/p?b=true&c=false&d=1&d=2"
    assert build_url("https://x.test", "p", {"a": None}) == "https://x.test/p"
    assert build_url("https://x.test", "p") == "https://x.test/p"


async def test_get_json_and_text() -> None:
    transport = FakeTransport({"/j": {"ok": 1}, "/t": "hello"})
    http = fake_http(transport)
    assert await http.get_json("https://x.test/j") == {"ok": 1}
    assert await http.get_text("https://x.test/t") == "hello"
    assert http.stats() == {
        "requests": 2,
        "retries": 0,
        "failures": 0,
        "last_error": "",
    }


async def test_non_retryable_status_raises_at_once() -> None:
    http = fake_http(FakeTransport())
    with pytest.raises(HttpError) as info:
        await http.get("https://x.test/missing")
    assert info.value.status == 404 and info.value.url.endswith("/missing")
    assert http.failures == 1 and "HTTP 404" in http.last_error


async def test_retries_on_429_then_succeeds_honouring_retry_after() -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    transport = FakeTransport(
        {
            "/r": Sequenced(
                Response(429, b"", {"Retry-After": "3"}),
                Response(503, b"", {"retry-after": "bad"}),
                {"ok": True},
            )
        }
    )
    http = JsonHttp(transport=transport, sleep=sleep, min_interval=0, backoff=0.5)
    assert await http.get_json("https://x.test/r") == {"ok": True}
    assert waits == [3.0, 1.0]
    assert http.retries == 2


async def test_gives_up_after_max_retries_on_network_errors() -> None:
    transport = FakeTransport({"/n": OSError("down")})
    http = fake_http(transport, max_retries=2)
    with pytest.raises(HttpError) as info:
        await http.get("https://x.test/n")
    assert "after 3 attempts" in str(info.value) and info.value.status is None
    assert transport.count("/n") == 3
    transport = FakeTransport({"/s": Response(500, b"")})
    http = fake_http(transport, max_retries=0)
    with pytest.raises(HttpError) as info:
        await http.get("https://x.test/s")
    assert info.value.status == 500


async def test_post_json_sends_a_json_body_with_its_content_type() -> None:
    seen: list[dict[str, str]] = []
    transport = FakeTransport({"/books": [{"asset_id": "a"}]})

    async def spy(
        url: str,
        timeout: float,
        headers: Mapping[str, str],
        data: bytes | None = None,
    ) -> Response:
        seen.append(dict(headers))
        return await transport(url, timeout, headers, data)

    http = JsonHttp(transport=spy, min_interval=0.0)
    assert await http.post_json("https://x.test/books", [{"token_id": "a"}]) == [
        {"asset_id": "a"}
    ]
    assert transport.bodies == [b'[{"token_id": "a"}]']
    assert seen[0]["Content-Type"] == "application/json"
    assert await http.get_json("https://x.test/books") == [{"asset_id": "a"}]
    assert "Content-Type" not in seen[1]


async def test_post_json_rejects_a_reply_that_is_not_json() -> None:
    http = fake_http(FakeTransport({"/b": "{not json"}))
    with pytest.raises(HttpError):
        await http.post_json("https://x.test/b", [])
    assert http.failures == 1


async def test_invalid_json_is_an_error() -> None:
    http = fake_http(FakeTransport({"/b": "{not json"}))
    with pytest.raises(HttpError):
        await http.get_json("https://x.test/b")
    assert http.failures == 1


async def test_pacing_waits_between_requests_to_one_host() -> None:
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    clock = Clock(100.0)
    http = JsonHttp(
        transport=FakeTransport({"/": {}}),
        sleep=sleep,
        clock=clock,
        min_interval=0.5,
    )
    await http.get("https://a.test/1")
    await http.get("https://a.test/2")
    await http.get("https://b.test/1")
    assert waits == [0.5]


def test_negative_retries_rejected() -> None:
    with pytest.raises(ValueError):
        JsonHttp(max_retries=-1)


def test_fetch_returns_body_and_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class Reply(io.BytesIO):
        status = 200
        headers = {"A": "b"}

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        http_mod.urllib.request, "urlopen", lambda r, timeout: Reply(b"x")
    )
    assert http_mod._fetch("https://x.test", 1, {}) == Response(200, b"x", {"A": "b"})

    def boom(request: object, timeout: float) -> None:
        raise urllib.error.HTTPError(
            "https://x.test",
            429,
            "slow",
            {"Retry-After": "1"},  # type: ignore[arg-type]
            io.BytesIO(b"no"),
        )

    monkeypatch.setattr(http_mod.urllib.request, "urlopen", boom)
    reply = http_mod._fetch("https://x.test", 1, {})
    assert reply.status == 429 and reply.body == b"no"

    def boom_empty(request: object, timeout: float) -> None:
        raise urllib.error.HTTPError(
            "https://x.test", 500, "err", None, None  # type: ignore[arg-type]
        )

    monkeypatch.setattr(http_mod.urllib.request, "urlopen", boom_empty)
    reply = http_mod._fetch("https://x.test", 1, {})
    assert reply.status == 500 and reply.headers == {}


def test_fetch_posts_its_data(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[bytes | None] = []

    class Reply(io.BytesIO):
        status = 200
        headers: dict[str, str] = {}

        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def capture(request: urllib.request.Request, timeout: float) -> Reply:
        sent.append(request.data)  # type: ignore[arg-type]
        return Reply(b"[]")

    monkeypatch.setattr(http_mod.urllib.request, "urlopen", capture)
    assert http_mod._fetch("https://x.test", 1, {}, b"{}").body == b"[]"
    assert sent == [b"{}"]


async def test_urllib_transport_runs_fetch_in_a_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        http_mod, "_fetch", lambda u, t, h, d: Response(200, u.encode() + (d or b""))
    )
    assert (await urllib_transport("https://x.test", 1, {})).body == b"https://x.test"
    reply = await urllib_transport("https://x.test", 1, {}, b"!")
    assert reply.body == b"https://x.test!"
