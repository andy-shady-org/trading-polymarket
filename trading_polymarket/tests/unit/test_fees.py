from __future__ import annotations

import pytest

from trading_polymarket.fees import FeeSchedule


def test_taker_fee_follows_the_published_formula() -> None:
    fee = FeeSchedule(rate=0.05)
    # 100 shares at 0.40: 100 x 0.05 x 0.4 x 0.6 = 1.2
    assert fee.taker_fee(100, 0.40) == pytest.approx(1.2)
    assert fee.per_share(0.5) == pytest.approx(0.0125)


def test_fee_is_rounded_to_five_decimals_and_zero_below_it() -> None:
    fee = FeeSchedule(rate=0.03)
    assert fee.taker_fee(0.0001, 0.5) == 0.0
    assert fee.taker_fee(1.234567, 0.37) == round(1.234567 * 0.03 * 0.37 * 0.63, 5)


def test_free_market_and_non_positive_size_pay_nothing() -> None:
    assert FeeSchedule().free
    assert FeeSchedule().taker_fee(100, 0.5) == 0.0
    assert FeeSchedule(rate=0.07).taker_fee(0, 0.5) == 0.0


def test_exponent_and_price_clamping() -> None:
    fee = FeeSchedule(rate=0.1, exponent=2)
    assert fee.per_share(0.5) == pytest.approx(0.1 * 0.25**2)
    assert fee.per_share(1.5) == 0.0
    assert fee.per_share(-1) == 0.0


@pytest.mark.parametrize(
    "kwargs", [{"rate": -0.1}, {"exponent": 0}, {"rebate_rate": -1}]
)
def test_invalid_schedules_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        FeeSchedule(**kwargs)


def test_from_gamma_reads_the_schedule_and_round_trips() -> None:
    raw = {"rate": 0.07, "exponent": 1, "takerOnly": True, "rebateRate": 0.2}
    fee = FeeSchedule.from_gamma(raw)
    assert (fee.rate, fee.exponent, fee.taker_only, fee.rebate_rate) == (
        0.07,
        1.0,
        True,
        0.2,
    )
    assert FeeSchedule.from_gamma(fee.to_dict()) == fee


def test_from_gamma_defaults_for_missing_or_malformed() -> None:
    assert FeeSchedule.from_gamma(None, default_rate=0.07).rate == 0.07
    assert FeeSchedule.from_gamma({"rate": "x"}, default_rate=0.03).rate == 0.03
    assert FeeSchedule.from_gamma({}).rate == 0.0
