"""Unit tests for ``research/rewards.py``: the liquidity-rewards scan (FEAT-153)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trading_polymarket.book import OrderBook
from trading_polymarket.clients.clob import ClobClient
from trading_polymarket.clients.gamma import GammaClient
from trading_polymarket.clients.http import Response
from trading_polymarket.research import rewards
from trading_polymarket.research.rewards import (
    Quote,
    RewardTerms,
    default_out,
    estimate,
    maker_score,
    order_score,
    parse_terms,
    scan,
    scan_row,
    shares_within,
    side_score,
    write_rows,
)
from trading_polymarket.tests.support.fakes import FakeTransport, fake_http

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC).timestamp()
TERMS = RewardTerms("0xa", 100.0, 20.0, 4.5)


def raw_terms(
    cid: str = "0xa", rate: float | None = 100.0, **extra: Any
) -> dict[str, Any]:
    return {
        "condition_id": cid,
        "rewards_max_spread": 4.5,
        "rewards_min_size": 20,
        "total_daily_rate": rate,
        **extra,
    }


def gamma_row(cid: str = "0xa", **extra: Any) -> dict[str, Any]:
    return {
        "conditionId": cid,
        "question": f"Q {cid}?",
        "slug": f"q-{cid}",
        "clobTokenIds": json.dumps([f"{cid}-yes", f"{cid}-no"]),
        "endDate": "2026-11-05T12:00:00Z",
        "volume24hr": 1234.5,
        "feeSchedule": {"rate": 0.04},
        "rewardsMinSize": 20,
        "rewardsMaxSpread": 4.5,
        **extra,
    }


def book(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> OrderBook:
    return OrderBook.from_levels("t", bids, asks)


def test_terms_are_read_or_refused() -> None:
    assert RewardTerms.from_api(raw_terms()) == TERMS
    summed = raw_terms(
        rate=None, rewards_config=[{"rate_per_day": 3}, {"rate_per_day": None}]
    )
    assert RewardTerms.from_api(summed) == RewardTerms("0xa", 3.0, 20.0, 4.5)
    assert RewardTerms.from_api(raw_terms(rate=None)) is None  # no config: pays 0
    assert RewardTerms.from_api({"condition_id": "0xa"}) is None
    assert RewardTerms.from_api(raw_terms(rewards_min_size="x")) is None
    assert RewardTerms.from_api(raw_terms(cid="")) is None
    assert RewardTerms.from_api(raw_terms(rewards_max_spread=0)) is None
    assert parse_terms([raw_terms(), {"bad": 1}]) == [TERMS]


def test_scores_follow_polymarkets_formula() -> None:
    assert order_score(1.0, 20, 4.5) == pytest.approx((3.5 / 4.5) ** 2 * 20)
    assert order_score(4.5, 20, 4.5) == 0.0 and order_score(1.0, 0, 4.5) == 0.0
    levels = book([(0.49, 100), (0.40, 50)], []).bids
    assert side_score(levels, 0.50, 4.5) == pytest.approx(order_score(1.0, 100, 4.5))
    assert shares_within(levels, 0.50, 4.5) == 100.0
    assert maker_score(9.0, 3.0, 0.5) == 3.0  # two-sided, in range: the min
    assert maker_score(9.0, 0.0, 0.5) == 3.0  # one-sided, in range: a third
    assert maker_score(9.0, 0.0, 0.05) == 0.0  # below 0.10: both sides or nothing
    assert maker_score(9.0, 0.0, 0.95) == 0.0  # above 0.90 too


def test_the_estimate_shares_the_pool_with_the_book() -> None:
    thin = book([(0.49, 20)], [(0.51, 20)])  # one 20-share maker each side
    found = estimate(thin, TERMS, Quote())
    assert found.competition == pytest.approx(order_score(1.0, 20, 4.5))
    assert found.two_sided == pytest.approx(50.0)  # half the pool
    assert found.one_sided == pytest.approx(100.0 * (1 / 3) / (1 / 3 + 1))
    assert found.capital == pytest.approx(20 * 0.98)
    small = estimate(thin, TERMS, Quote(shares=10))
    assert small.two_sided == 0.0  # under the minimum size: no score
    wide = estimate(thin, TERMS, Quote(cents=5))
    assert wide.two_sided == 0.0  # outside the reward spread


def test_a_row_flags_what_cannot_be_trusted() -> None:
    clean = scan_row(TERMS, gamma_row(), book([(0.49, 20)], [(0.51, 20)]), Quote(), NOW)
    assert clean.note == "" and clean.mid == pytest.approx(0.50)
    assert clean.reward_two_sided == pytest.approx(50.0)
    assert clean.reward_per_dollar == pytest.approx(50.0 / 19.6, abs=1e-4)
    assert clean.tokens == ("0xa-yes", "0xa-no") and clean.hours_to_end == 24.0
    assert clean.fee_rate == 0.04 and clean.to_dict()["tokens"] == ["0xa-yes", "0xa-no"]
    ended = scan_row(
        TERMS,
        gamma_row(endDate="2026-11-03T12:00:00Z"),
        book([(0.01, 5)], [(0.99, 5)]),
        Quote(),
        NOW,
    )
    assert ended.note == "ended, wide book"
    one = scan_row(TERMS, gamma_row(), book([(0.49, 5)], []), Quote(), NOW)
    assert one.note == "one-sided book" and one.best_bid == 0.49
    none = scan_row(TERMS, {}, None, Quote(shares=50), NOW)
    assert none.note == "no book" and none.quote_shares == 50 and none.tokens == ()
    odd = gamma_row(
        endDate="soon", clobTokenIds="not json", feeSchedule=None, volume24hr=None
    )
    row = scan_row(TERMS, odd, book([(0.49, 20)], [(0.51, 20)]), Quote(cents=9), NOW)
    assert row.hours_to_end is None and row.tokens == () and row.fee_rate == 0.0
    assert row.reward_two_sided == 0.0 and row.reward_per_dollar == 0.0
    listed = scan_row(TERMS, gamma_row(clobTokenIds=["a", "b"]), None, Quote(), NOW)
    assert listed.tokens == ("a", "b")
    assert (
        scan_row(TERMS, gamma_row(clobTokenIds="{}"), None, Quote(), NOW).tokens == ()
    )


def test_a_quote_that_ties_up_nothing_earns_nothing_a_dollar() -> None:
    row = scan_row(
        TERMS, gamma_row(), book([(0.49, 20)], [(0.51, 20)]), Quote(cents=50), NOW
    )
    assert row.capital == 0.0 and row.reward_per_dollar == 0.0


async def test_the_scan_ranks_clean_books_first(tmp_path: Path) -> None:
    def books(url: str) -> Any:
        if "0xb-yes" in url:
            return {
                "bids": [{"price": "0.01", "size": "5"}],
                "asks": [{"price": "0.99", "size": "5"}],
            }
        if "0xd-yes" in url:
            return Response(404, b"{}")
        return {
            "bids": [{"price": "0.49", "size": "20"}],
            "asks": [{"price": "0.51", "size": "20"}],
        }

    transport = FakeTransport(
        {
            "/rewards/markets/current": {
                "data": [
                    raw_terms("0xa", 100),
                    raw_terms("0xb", 500),
                    raw_terms("0xc", 1),
                    raw_terms("0xd", 50),
                    raw_terms("0xe", 40),
                    {"bad": 1},
                ],
                "next_cursor": "LTE=",
            },
            "/markets?": [gamma_row("0xa"), gamma_row("0xb"), gamma_row("0xd")],
            "/book": books,
        }
    )
    http = fake_http(transport, max_retries=0)
    lines: list[str] = []
    total, rows = await scan(
        ClobClient(http, base_url="https://c.test"),
        GammaClient(http, base_url="https://g.test"),
        limit=4,
        min_daily_rate=2,
        now=NOW,
        progress=lines.append,
    )
    assert total == 5 and lines == ["5 markets pay rewards; scanning the 4 best paid"]
    assert [r.condition_id for r in rows] == ["0xa", "0xb", "0xd", "0xe"]
    assert rows[1].note == "wide book" and rows[2].note == "no book"
    assert rows[3].note == "no book" and rows[3].question == ""  # Gamma did not know it
    quiet = await scan(
        ClobClient(http, base_url="https://c.test"),
        GammaClient(http, base_url="https://g.test"),
    )
    assert quiet[0] == 5
    path = write_rows(rows, tmp_path / "r" / "x.jsonl")
    assert len(path.read_text().splitlines()) == 4
    assert default_out(NOW) == "data/rewards/rewards-20261104T120000Z.jsonl"
    assert rewards._number("x") is None
