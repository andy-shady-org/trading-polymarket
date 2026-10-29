from __future__ import annotations

import json

import pytest

from trading_polymarket.markets import (
    Market,
    index_by_token,
    markets_from_event,
    parse_time,
)
from trading_polymarket.tests.support.factories import (
    NO,
    NOW,
    YES,
    fixture,
    gamma_market,
    market,
    resolved,
)


def test_from_gamma_decodes_json_string_fields() -> None:
    m = market()
    assert m.token_ids == (YES, NO)
    assert m.outcomes == ("Yes", "No")
    assert m.outcome_prices == (0.6, 0.4)
    assert m.fee.rate == 0.05
    assert m.best_ask == 0.61 and m.min_order_size == 5
    assert m.end_time == pytest.approx(NOW + 24 * 3600)
    assert m.tradable and not m.resolved


def test_real_fixture_parses() -> None:
    raw = fixture("resolved_market.json")
    m = Market.from_gamma(raw)
    assert m.resolved
    assert m.event_slug  # taken from events[0]
    assert m.payout(m.token_ids[0]) in (0.0, 1.0)


def test_lists_are_accepted_as_well_as_json_strings() -> None:
    m = Market.from_gamma(
        gamma_market(
            outcomes=["Yes", "No"], clobTokenIds=[YES, NO], outcomePrices="not json"
        )
    )
    assert m.token_ids == (YES, NO)
    assert m.outcome_prices == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"clobTokenIds": json.dumps([YES])},
        {"clobTokenIds": None},
        {"outcomes": json.dumps(["Yes"])},
        {"clobTokenIds": json.dumps({"a": 1})},
    ],
)
def test_untradable_shapes_are_refused(overrides: dict) -> None:
    with pytest.raises(ValueError):
        Market.from_gamma(gamma_market(**overrides))


def test_bad_numbers_fall_back() -> None:
    m = market(bestBid=True, bestAsk="x", volume24hr=None, orderPriceMinTickSize=None)
    assert m.best_bid is None and m.best_ask is None
    assert m.volume_24h == 0.0 and m.tick_size == 0.01


def test_missing_fee_schedule_uses_default_only_when_fees_enabled() -> None:
    charged = Market.from_gamma(gamma_market(feeSchedule=None), default_fee_rate=0.07)
    free = Market.from_gamma(
        gamma_market(feeSchedule=None, feesEnabled=False), default_fee_rate=0.07
    )
    assert charged.fee.rate == 0.07
    assert free.fee.rate == 0.0


def test_event_fields_and_tags() -> None:
    event = {
        "id": 7,
        "slug": "ev",
        "title": "Event",
        "description": "desc",
        "tags": [{"slug": "politics"}, {"label": "Label"}, {"x": 1}, "bad"],
    }
    m = market(event=event)
    assert (m.event_id, m.event_slug, m.event_title) == ("7", "ev", "Event")
    assert m.tags == ("politics", "Label")
    assert m.description == "desc"
    nested = Market.from_gamma(gamma_market(events=["bad"]))
    assert nested.event_id == ""


def test_resolution_and_payouts() -> None:
    won = resolved(winner=1)
    assert won.resolved
    assert won.payout(NO) == 1.0 and won.payout(YES) == 0.0
    assert market().payout(YES) is None
    assert not market(closed=True).resolved
    assert not market(closed=True, outcomePrices="[]").resolved
    assert not won.tradable


def test_price_of_each_token() -> None:
    m = market()
    assert m.price_of(YES) == 0.6 and m.price_of(NO) == 0.4
    assert market(outcomePrices="[]").price_of(YES) is None


def test_tokens_helpers() -> None:
    m = market()
    assert m.yes_token == YES and m.no_token == NO
    assert m.complement(YES) == NO and m.complement(NO) == YES
    assert m.outcome_of(NO) == "No"
    with pytest.raises(KeyError):
        m.token_index("nope")
    three = Market.from_gamma(
        gamma_market(
            clobTokenIds=json.dumps(["a", "b", "c"]),
            outcomes=json.dumps(["A", "B", "C"]),
            outcomePrices=json.dumps(["0.1", "0.2", "0.7"]),
        )
    )
    with pytest.raises(ValueError):
        three.complement("a")


def test_hours_to_close_and_label() -> None:
    m = market(groupItemTitle="")
    assert m.hours_to_close(NOW) == pytest.approx(24)
    assert market(endDate=None).hours_to_close(NOW) is None
    assert m.label(YES) == "Will it happen? · Yes"
    assert market(groupItemTitle="Bucket").label(NO) == "Bucket · No"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-28T12:00:00Z", NOW),
        ("2026-10-28T12:00:00+00", NOW),
        ("2026-10-28T12:00:00", NOW),
        ("", None),
        (None, None),
        ("not a date", None),
    ],
)
def test_parse_time(text: object, expected: float | None) -> None:
    assert parse_time(text) == expected


def test_markets_from_event_skips_malformed() -> None:
    event = {
        "id": "1",
        "markets": [gamma_market(), {"id": "x"}, "junk"],
    }
    found = markets_from_event(event)
    assert len(found) == 1 and found[0].event_id == "1"
    assert index_by_token(found) == {YES: found[0], NO: found[0]}
    assert markets_from_event({}) == []
