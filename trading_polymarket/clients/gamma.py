"""The Gamma API: Polymarket's free, keyless market catalogue.

Endpoints used (docs/DATA-SOURCES.md has the full notes):

* ``GET /markets/keyset`` and ``GET /events/keyset`` - cursor-paged listings
  (``limit`` <= 100, ``after_cursor`` -> ``next_cursor``), filterable by
  ``closed``, ``tag_slug``, ``end_date_min`` / ``end_date_max``, ``order``;
* ``GET /markets?clob_token_ids=...`` - markets by outcome token id (open
  ones only, unless ``closed=true``, which returns the closed ones only);
* ``GET /public-search?q=...`` - text search over events.

Published limits are 300 requests / 10 s for ``/markets`` and 500 / 10 s for
``/events``; Cloudflare throttles rather than rejects, and the shared
:class:`~trading_polymarket.clients.http.JsonHttp` paces well below that.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from typing import Any

from trading_polymarket.clients.http import JsonHttp, build_url
from trading_polymarket.markets import Market, markets_from_event

GAMMA_URL = "https://gamma-api.polymarket.com"
PAGE_LIMIT = 100
TOKENS_PER_LOOKUP = 20


def _items(payload: Any, key: str) -> tuple[list[Any], str | None]:
    """``(items, next_cursor)`` from a keyset page or a bare list."""
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, Mapping):
        items = payload.get(key)
        cursor = payload.get("next_cursor") or None
        return (items if isinstance(items, list) else []), cursor
    return [], None


class GammaClient:
    def __init__(
        self, http: JsonHttp, *, base_url: str = GAMMA_URL, default_fee_rate: float = 0
    ) -> None:
        self.http = http
        self.base_url = base_url
        self.default_fee_rate = default_fee_rate

    def _url(self, path: str, params: Mapping[str, Any] | None = None) -> str:
        return build_url(self.base_url, path, params)

    def _market(self, raw: Mapping[str, Any]) -> Market | None:
        try:
            return Market.from_gamma(raw, default_fee_rate=self.default_fee_rate)
        except ValueError:
            return None

    async def _pages(
        self, path: str, key: str, params: Mapping[str, Any], max_pages: int
    ) -> AsyncIterator[list[Any]]:
        query = {"limit": PAGE_LIMIT, **params}
        cursor: str | None = None
        for _ in range(max(1, max_pages)):
            payload = await self.http.get_json(
                self._url(path, {**query, "after_cursor": cursor})
            )
            items, cursor = _items(payload, key)
            yield items
            if not cursor or not items:
                return

    # -- raw listings ---------------------------------------------------------
    async def raw_markets(
        self, *, max_pages: int = 1, **params: Any
    ) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        async for items in self._pages("/markets/keyset", "markets", params, max_pages):
            found.extend(i for i in items if isinstance(i, dict))
        return found

    async def raw_events(
        self, *, max_pages: int = 1, **params: Any
    ) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        async for items in self._pages("/events/keyset", "events", params, max_pages):
            found.extend(i for i in items if isinstance(i, dict))
        return found

    # -- parsed ---------------------------------------------------------------
    async def markets(self, *, max_pages: int = 1, **params: Any) -> list[Market]:
        """Tradable-shaped markets from ``/markets/keyset`` (malformed skipped)."""
        raw = await self.raw_markets(max_pages=max_pages, **params)
        return [m for m in (self._market(r) for r in raw) if m is not None]

    async def events(
        self, *, max_pages: int = 1, **params: Any
    ) -> list[tuple[dict[str, Any], list[Market]]]:
        """``(event, its markets)`` pairs from ``/events/keyset``."""
        raw = await self.raw_events(max_pages=max_pages, **params)
        return [
            (event, markets_from_event(event, default_fee_rate=self.default_fee_rate))
            for event in raw
        ]

    async def _lookup(
        self, tokens: Sequence[str], *, closed: bool | None
    ) -> dict[str, Market]:
        """One ``/markets?clob_token_ids=`` pass over ``tokens``, in batches."""
        found: dict[str, Market] = {}
        for start in range(0, len(tokens), TOKENS_PER_LOOKUP):
            batch = list(tokens[start : start + TOKENS_PER_LOOKUP])
            params = {"clob_token_ids": batch, "limit": len(batch) * 2}
            payload = await self.http.get_json(
                self._url("/markets", {**params, "closed": closed})
            )
            items, _ = _items(payload, "markets")
            for raw in items:
                market = self._market(raw) if isinstance(raw, Mapping) else None
                if market is not None:
                    found[market.market_id] = market
        return found

    async def markets_by_tokens(self, token_ids: Iterable[str]) -> list[Market]:
        """Markets owning ``token_ids``, open or closed.

        Gamma's token lookup leaves closed markets out unless asked with
        ``closed=true`` (and then leaves the open ones out), so the tokens the
        first pass did not find are asked for again as closed. Without this a
        held token's market vanished at its close and its resolution was
        never seen (TP-9).
        """
        tokens = sorted({str(t) for t in token_ids if t})
        found = await self._lookup(tokens, closed=None)
        seen = {token for market in found.values() for token in market.token_ids}
        missing = [token for token in tokens if token not in seen]
        if missing:
            found.update(await self._lookup(missing, closed=True))
        return list(found.values())

    async def market_by_token(self, token_id: str) -> Market | None:
        for market in await self.markets_by_tokens([token_id]):
            if token_id in market.token_ids:
                return market
        return None

    async def search_events(
        self, query: str, *, status: str = "active", limit: int = 20
    ) -> list[dict[str, Any]]:
        payload = await self.http.get_json(
            self._url(
                "/public-search",
                {"q": query, "events_status": status, "limit_per_type": limit},
            )
        )
        events = payload.get("events") if isinstance(payload, Mapping) else None
        return [e for e in events or [] if isinstance(e, dict)]

    async def closed_markets(
        self,
        *,
        end_date_min: str,
        end_date_max: str,
        max_pages: int = 10,
        tag_slug: str | None = None,
    ) -> list[Market]:
        """Markets that closed between two ISO dates (resolution research)."""
        return await self.markets(
            max_pages=max_pages,
            closed=True,
            end_date_min=end_date_min,
            end_date_max=end_date_max,
            tag_slug=tag_slug,
        )


def resolved_only(markets: Sequence[Market]) -> list[Market]:
    return [m for m in markets if m.resolved]


__all__ = ["GAMMA_URL", "GammaClient", "PAGE_LIMIT", "resolved_only"]
