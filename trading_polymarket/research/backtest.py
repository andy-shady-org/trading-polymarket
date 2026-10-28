"""Calibration and the favourite-lane backtest, on collected history.

Both use only what was knowable at the time:

* :func:`observations` samples each market's price ``h`` hours before close
  (the last print at or before that moment) for both tokens, labelled with
  whether the token won;
* :func:`calibrate` builds a :class:`CalibrationTable` from markets that
  closed **before** ``split`` (the training set);
* :func:`backtest_favourite` replays only markets that closed **after**
  ``split`` (the test set) with the trained table: for each market it walks
  the entry horizons from the furthest to the nearest, takes the first entry
  the live lane would have taken (price band, calibrated edge after the
  modelled spread and the market's fee), and holds it to resolution.

Trades are written in trading-core's audit format, so
``trading-core-audit verdict --path <file> --rules
configs/verdict/favourite.json`` gives the GO/No-Go answer for the
backtest stage (docs/GO-NO-GO.md stage 0).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from trading_polymarket.calibration import CalibrationTable, Observation
from trading_polymarket.config import LANE_FAVOURITE, FavouriteLane
from trading_polymarket.fees import FeeSchedule
from trading_polymarket.research.history import HistoryRow
from trading_polymarket.research.records import round_trip
from trading_polymarket.strategies.common import kelly_fraction, net_edge

DEFAULT_HORIZONS = (72.0, 48.0, 24.0, 12.0, 6.0, 3.0, 1.0)


def observations(
    rows: Iterable[HistoryRow], horizons: Sequence[float] = DEFAULT_HORIZONS
) -> Iterator[Observation]:
    for row in rows:
        for hours in horizons:
            price = row.price_at(row.end_time - hours * 3600.0)
            if price is None or not 0.0 < price < 1.0:
                continue
            yield Observation(price, hours, row.winner == 0)
            yield Observation(1.0 - price, hours, row.winner == 1)


def split_rows(
    rows: Sequence[HistoryRow], split: float
) -> tuple[list[HistoryRow], list[HistoryRow]]:
    return (
        [r for r in rows if r.end_time < split],
        [r for r in rows if r.end_time >= split],
    )


def calibrate(
    rows: Sequence[HistoryRow],
    *,
    horizons: Sequence[float] = DEFAULT_HORIZONS,
    prior_strength: float = 50.0,
) -> CalibrationTable:
    table = CalibrationTable.build(
        observations(rows, horizons), prior_strength=prior_strength
    )
    table.meta = {
        "markets": len(rows),
        "first_close": min((r.end_time for r in rows), default=None),
        "last_close": max((r.end_time for r in rows), default=None),
        "horizons": list(horizons),
    }
    return table


@dataclass(frozen=True)
class BacktestResult:
    records: list[dict[str, Any]]
    trades: int
    markets: int
    net: float
    scores: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "markets": self.markets,
            "trades": self.trades,
            "net": self.net,
        }
        if self.scores:
            out["scores"] = self.scores
        return out


def brier_scores(
    forecasts: Sequence[tuple[float, float, float, bool]],
) -> dict[str, Any]:
    """Brier scores of ``(model, market, blend, outcome)`` rows (lower is better).

    The question a model must answer before it trades: is it better
    calibrated than the price it trades against?
    """
    if not forecasts:
        return {}
    n = len(forecasts)

    def score(index: int) -> float:
        return round(sum((row[index] - row[3]) ** 2 for row in forecasts) / n, 5)

    return {"buckets": n, "model": score(0), "market": score(1), "blend": score(2)}


def backtest_favourite(
    rows: Sequence[HistoryRow],
    table: CalibrationTable,
    lane: FavouriteLane,
    *,
    bankroll: float = 1000.0,
    half_spread: float = 0.005,
    horizons: Sequence[float] = DEFAULT_HORIZONS,
) -> BacktestResult:
    """Replay the favourite lane on ``rows`` (the test set)."""
    records: list[dict[str, Any]] = []
    trades = 0
    net = 0.0
    for row in rows:
        fee = FeeSchedule(rate=row.fee_rate, exponent=row.fee_exponent)
        for hours in sorted(
            (h for h in horizons if lane.min_hours <= h <= lane.max_hours),
            reverse=True,
        ):
            moment = row.end_time - hours * 3600.0
            entry = _favourite_entry(row, moment, hours, table, lane, fee, half_spread)
            if entry is None:
                continue
            index, cost, fair, samples = entry
            kelly = kelly_fraction(fair, cost + fee.per_share(cost))
            notional = min(lane.max_notional, lane.kelly_fraction * kelly * bankroll)
            if notional < lane.min_notional:
                continue
            payout = 1.0 if row.winner == index else 0.0
            entry_fee = round(notional / cost * fee.per_share(cost), 5)
            records.extend(
                round_trip(
                    instrument_id=row.token_ids[index],
                    name=(row.group_item_title or row.question)[:60],
                    strategy=LANE_FAVOURITE,
                    reason=f"backtest favourite {fair:.3f} vs {cost:.3f}",
                    entry_time=moment,
                    entry_price=cost,
                    notional=notional,
                    entry_fee=entry_fee,
                    exit_time=row.end_time,
                    exit_price=payout,
                    metrics={
                        "fair": round(fair, 4),
                        "calibration_n": samples,
                        "hours_to_close": hours,
                        "fee_rate": row.fee_rate,
                    },
                )
            )
            trades += 1
            net += notional / cost * payout - notional - entry_fee
            break
    return BacktestResult(records, trades, len(rows), round(net, 4))


def _favourite_entry(
    row: HistoryRow,
    moment: float,
    hours: float,
    table: CalibrationTable,
    lane: FavouriteLane,
    fee: FeeSchedule,
    half_spread: float,
) -> tuple[int, float, float, int] | None:
    for index in (0, 1):
        price = row.price_at(moment, index)
        if price is None:
            continue
        cost = min(0.999, price + half_spread)
        if not lane.min_price <= cost <= lane.max_price:
            continue
        samples = table.samples(cost, hours)
        if samples < lane.min_samples:
            continue
        fair = table.win_rate(cost, hours)
        if net_edge(fair, cost, fee) >= lane.min_edge:
            return index, cost, fair, samples
    return None


__all__ = [
    "BacktestResult",
    "brier_scores",
    "DEFAULT_HORIZONS",
    "backtest_favourite",
    "calibrate",
    "observations",
    "split_rows",
]
