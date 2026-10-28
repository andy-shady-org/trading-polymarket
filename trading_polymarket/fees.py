"""Polymarket taker fees.

Since Fee Structure V2 (2026-03-30) every market carries a ``feeSchedule``::

    {"rate": 0.05, "exponent": 1, "takerOnly": true, "rebateRate": 0.25}

and a taker pays, in USDC/pUSD, ``fee = shares × rate × (p × (1 − p))^exponent``
where ``p`` is the trade price. Fees are rounded to 5 decimals (amounts below
0.00001 round to zero). Makers pay nothing; geopolitics / world-events markets
have ``rate = 0``. A market without a schedule is treated as fee-free only when
the caller says so (``default_rate``): paper fills must never be cheaper than
live ones, so an unknown schedule should be priced at the category rate.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

FEE_DECIMALS = 5


@dataclass(frozen=True)
class FeeSchedule:
    rate: float = 0.0
    exponent: float = 1.0
    taker_only: bool = True
    rebate_rate: float = 0.0

    def __post_init__(self) -> None:
        if self.rate < 0 or self.exponent <= 0 or self.rebate_rate < 0:
            raise ValueError("fee rate/rebate must be >= 0 and exponent > 0")

    @classmethod
    def from_gamma(cls, data: Any, *, default_rate: float = 0.0) -> FeeSchedule:
        """Parse a Gamma ``feeSchedule``; missing or malformed: ``default_rate``."""
        if not isinstance(data, Mapping):
            return cls(rate=default_rate)
        try:
            return cls(
                rate=float(data.get("rate") or 0.0),
                exponent=float(data.get("exponent") or 1.0),
                taker_only=bool(data.get("takerOnly", True)),
                rebate_rate=float(data.get("rebateRate") or 0.0),
            )
        except (TypeError, ValueError):
            return cls(rate=default_rate)

    @property
    def free(self) -> bool:
        return self.rate == 0.0

    def per_share(self, price: float) -> float:
        """Fee per share at ``price`` (unrounded), for edge arithmetic."""
        p = min(1.0, max(0.0, float(price)))
        return self.rate * (p * (1.0 - p)) ** self.exponent

    def taker_fee(self, shares: float, price: float) -> float:
        """Fee for one taker fill of ``shares`` at ``price``, rounded as charged."""
        if shares <= 0 or self.free:
            return 0.0
        return round(shares * self.per_share(price), FEE_DECIMALS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rate": self.rate,
            "exponent": self.exponent,
            "takerOnly": self.taker_only,
            "rebateRate": self.rebate_rate,
        }


__all__ = ["FEE_DECIMALS", "FeeSchedule"]
