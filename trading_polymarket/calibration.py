"""Calibration: how often a token priced ``p`` actually won.

A :class:`CalibrationTable` counts, per price bin and hours-to-close bin, how
many observed tokens won. It is built from **real resolved markets**
(``trading-polymarket history`` then ``calibrate``) and answers
:meth:`win_rate` with a shrunk estimate::

    (wins + k * mid) / (n + k)

so a thin cell stays close to the market price (no edge) and only a well
sampled cell can claim one. With no table at all every price maps to itself:
the favourite lane then finds no edge and trades nothing, which is the safe
default.
"""

from __future__ import annotations

import bisect
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_PRICE_EDGES = (
    0.0, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80,
    0.85, 0.90, 0.93, 0.95, 0.97, 0.99, 1.0,
)  # fmt: skip
DEFAULT_HOUR_EDGES = (0.0, 6.0, 24.0, 72.0, 24.0 * 365)
VERSION = 1


@dataclass(frozen=True)
class Observation:
    price: float
    hours: float
    won: bool


@dataclass
class CalibrationTable:
    price_edges: tuple[float, ...] = DEFAULT_PRICE_EDGES
    hour_edges: tuple[float, ...] = DEFAULT_HOUR_EDGES
    prior_strength: float = 50.0
    # cell key -> [observations, wins, sum of prices]
    counts: dict[str, list[float]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.price_edges = tuple(float(e) for e in self.price_edges)
        self.hour_edges = tuple(float(e) for e in self.hour_edges)
        for edges in (self.price_edges, self.hour_edges):
            if len(edges) < 2 or list(edges) != sorted(set(edges)):
                raise ValueError("bin edges must be strictly increasing")
        self.prior_strength = float(self.prior_strength)
        if self.prior_strength < 0:
            raise ValueError("prior_strength must not be negative")

    # -- bins -------------------------------------------------------------------
    @staticmethod
    def _bin(edges: Sequence[float], value: float) -> int:
        index = bisect.bisect_right(edges, value) - 1
        return min(max(index, 0), len(edges) - 2)

    def key(self, price: float, hours: float) -> str:
        price_bin = self._bin(self.price_edges, price)
        return f"{price_bin}:{self._bin(self.hour_edges, hours)}"

    # -- building ---------------------------------------------------------------
    def add(self, observation: Observation) -> None:
        cell = self.counts.setdefault(
            self.key(observation.price, observation.hours), [0.0, 0.0, 0.0]
        )
        cell[0] += 1
        cell[1] += 1.0 if observation.won else 0.0
        cell[2] += observation.price

    @classmethod
    def build(
        cls, observations: Iterable[Observation], **options: Any
    ) -> CalibrationTable:
        table = cls(**options)
        for observation in observations:
            table.add(observation)
        return table

    # -- reading ----------------------------------------------------------------
    def samples(self, price: float, hours: float) -> int:
        return int(self.counts.get(self.key(price, hours), [0])[0])

    def win_rate(self, price: float, hours: float) -> float:
        """Shrunk empirical win rate for a token priced ``price`` now."""
        n, wins, total = self.counts.get(self.key(price, hours), [0.0, 0.0, 0.0])
        if n <= 0:
            return price
        # Shrink towards the cell's own average price (the market's view), then
        # shift by where inside the cell this price sits.
        mean_price = total / n
        rate = (wins + self.prior_strength * mean_price) / (n + self.prior_strength)
        return min(1.0, max(0.0, rate + (price - mean_price)))

    def edge(self, price: float, hours: float) -> float:
        return self.win_rate(price, hours) - price

    def rows(self) -> list[dict[str, Any]]:
        """One row per populated cell (for ``calibrate`` reports)."""
        out = []
        for key, (n, wins, total) in sorted(
            self.counts.items(), key=lambda kv: tuple(int(x) for x in kv[0].split(":"))
        ):
            p_bin, h_bin = (int(x) for x in key.split(":"))
            mean = total / n if n else 0.0
            out.append(
                {
                    "price_lo": self.price_edges[p_bin],
                    "price_hi": self.price_edges[p_bin + 1],
                    "hours_lo": self.hour_edges[h_bin],
                    "hours_hi": self.hour_edges[h_bin + 1],
                    "n": int(n),
                    "mean_price": mean,
                    "win_rate": wins / n if n else 0.0,
                    "shrunk": self.win_rate(mean, self.hour_edges[h_bin]),
                }
            )
        return out

    # -- persistence ------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "price_edges": list(self.price_edges),
            "hour_edges": list(self.hour_edges),
            "prior_strength": self.prior_strength,
            "counts": {k: list(v) for k, v in sorted(self.counts.items())},
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalibrationTable:
        if int(data.get("version", 0)) != VERSION:
            raise ValueError(f"unsupported calibration version {data.get('version')}")
        return cls(
            price_edges=tuple(data["price_edges"]),
            hour_edges=tuple(data["hour_edges"]),
            prior_strength=float(data.get("prior_strength", 50.0)),
            counts={str(k): [float(x) for x in v] for k, v in data["counts"].items()},
            meta=dict(data.get("meta") or {}),
        )

    def save(self, path: str | Path) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")
        return str(target)

    @classmethod
    def load(cls, path: str | Path) -> CalibrationTable:
        return cls.from_dict(json.loads(Path(path).read_text()))

    def sha256(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()


def load_or_identity(path: str) -> CalibrationTable:
    """The table at ``path``; an empty (identity, no-edge) table without one."""
    if path and Path(path).is_file():
        return CalibrationTable.load(path)
    return CalibrationTable(meta={"identity": True})


__all__ = [
    "CalibrationTable",
    "DEFAULT_HOUR_EDGES",
    "DEFAULT_PRICE_EDGES",
    "Observation",
    "load_or_identity",
]
