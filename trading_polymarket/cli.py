"""``trading-polymarket``: research and inspection commands (docs/CLI.md).

Trading itself runs through trading-core (``trading-core run --config ...``);
these commands collect evidence and look at what the lanes see:

=================  ==========================================================
``scan``           run the enabled lanes once on live data, print the signals
``weather``        model vs market for every open temperature event
``record``         dry-run the lanes every N seconds, log signals to JSONL
``arb``            record-only scan for binary-pair / neg-risk arbitrage
``bias``           measure each weather station's day-ahead forecast bias
``metars``         append recent METARs to the archive (intraday backtests)
``history``        collect resolved markets + price histories
``weather-history``collect resolved temperature events + price histories
``calibrate``      build the favourite lane's calibration table
``backtest``       replay a lane on collected history (audit-format output)
=================  ==========================================================

Every command is read-only towards Polymarket and uses free, keyless APIs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_polymarket import __version__
from trading_polymarket.config import LANES, PolymarketSettings
from trading_polymarket.module import PolymarketModule
from trading_polymarket.research import arb as arb_mod
from trading_polymarket.research import backtest as bt
from trading_polymarket.research import bias as bias_mod
from trading_polymarket.research import history as hist
from trading_polymarket.research import metar_archive, recorder
from trading_polymarket.research import weather_backtest as wbt
from trading_polymarket.research.records import append_jsonl
from trading_polymarket.strategies.weather import (
    WEATHER_TAG,
    WeatherEvent,
    WeatherModel,
    load_stations,
)

Printer = Callable[[str], None]


def module_settings(path: str | None) -> dict[str, Any]:
    """``module_settings`` of a trading-core config file (``{}`` without one)."""
    if not path:
        return {}
    data = json.loads(Path(path).read_text())
    settings = data.get("module_settings", {}) if isinstance(data, dict) else {}
    if not isinstance(settings, dict):
        raise ValueError("module_settings must be an object")
    return settings


def build_module(args: argparse.Namespace) -> PolymarketModule:
    settings = module_settings(getattr(args, "config", None))
    lanes = getattr(args, "lane", None)
    if lanes:
        for lane in LANES:
            entry = dict(settings.get(lane) or {})
            entry["enabled"] = lane in lanes
            settings[lane] = entry
    return PolymarketModule(**settings)


def _write(path: str, records: Sequence[dict[str, Any]]) -> str:
    target = Path(path)
    if target.exists():
        target.unlink()
    append_jsonl(target, records)
    return str(target)


def _fmt_signal(signal: Any) -> str:
    m = signal.metrics
    return (
        f"{signal.strategy:<9} {str(signal.name)[:44]:<44} "
        f"fair {m.get('fair', float('nan')):.3f} avg {m.get('avg_price', 0):.3f} "
        f"edge {signal.edge if signal.edge is not None else float('nan'):+.3f} "
        f"${signal.notional or 0:,.2f}"
    )


# -- commands ---------------------------------------------------------------
async def cmd_scan(args: argparse.Namespace, out: Printer) -> int:
    module = build_module(args)
    pipeline = module.pipeline()
    if pipeline is None:
        out("no lane is enabled")
        return 1
    out(f"pipeline: {pipeline.describe()}")
    result = await pipeline.run()
    out(
        f"{result.candidates} candidates, {len(result.signals)} signals, "
        f"{len(result.rejections)} rejected, {len(result.errors)} errors"
    )
    for signal in result.signals[: args.limit]:
        out(_fmt_signal(signal))
    for error in result.errors[:5]:
        out(f"error: {error}")
    return 0


async def cmd_weather(args: argparse.Namespace, out: Printer) -> int:
    module = build_module(args)
    lane = module.settings.weather
    model = WeatherModel(module.weather_client, lane, clock=module.clock)
    wanted = {c.lower() for c in args.city}
    for raw, markets in await module.gamma.events(
        max_pages=2, closed=False, tag_slug=WEATHER_TAG
    ):
        event = WeatherEvent.parse(raw, markets)
        if event is None or (wanted and event.city.lower() not in wanted):
            continue
        dist = await model.distribution(event)
        if dist is None or int(dist.metrics.get("lead_days", 9)) > lane.lead_days:
            continue
        out(
            f"\n{event.title} [{event.icao}] mu {dist.mu:.1f}°C sd {dist.sigma:.1f} "
            f"observed {dist.floor}"
        )
        for bucket in event.buckets:
            market = bucket.market
            p = dist.bucket_probability(bucket)
            ask = market.best_ask
            out(
                f"  {bucket.label:>10}  model {p:6.3f}  bid "
                f"{market.best_bid if market.best_bid is not None else '-':>6} ask "
                f"{ask if ask is not None else '-':>6}"
            )
    return 0


async def cmd_record(args: argparse.Namespace, out: Printer) -> int:
    module = build_module(args)
    total = await recorder.record(
        module,
        directory=args.out,
        cycles=args.cycles,
        interval=args.interval,
        progress=out,
    )
    out(f"{total} signals recorded in {args.out}")
    return 0


async def cmd_arb(args: argparse.Namespace, out: Printer) -> int:
    module = build_module(args)
    scanner = arb_mod.ArbScanner(
        module.gamma, module.books, min_profit=args.min_profit, min_size=args.min_size
    )
    found = await scanner.scan(max_pages=args.pages)
    append_jsonl(args.out, (o.to_dict() for o in found))
    for o in found[:20]:
        flag = " (augmented)" if o.augmented else ""
        out(
            f"{o.kind:<13} {o.title[:50]:<50} cost {o.cost:.4f} "
            f"profit {o.profit:.4f} x{o.size:,.0f}{flag}"
        )
    out(f"{len(found)} opportunities appended to {args.out}")
    return 0


async def cmd_bias(args: argparse.Namespace, out: Printer) -> int:
    module = build_module(args)
    stations = load_stations()
    if args.station:
        stations = {k: v for k, v in stations.items() if k in set(args.station)}
    table = await bias_mod.build_bias_table(
        module.weather_client,
        stations,
        models=module.settings.weather.models,
        days=args.days,
        progress=out,
    )
    out(f"bias table written to {bias_mod.save_table(table, args.out)}")
    return 0


async def cmd_metars(args: argparse.Namespace, out: Printer) -> int:
    module = build_module(args)
    stations = sorted(load_stations())
    new = await metar_archive.archive(
        module.weather_client, stations, directory=args.out, progress=out
    )
    out(f"{new} new METARs archived in {args.out} ({len(stations)} stations)")
    return 0


async def cmd_history(args: argparse.Namespace, out: Printer) -> int:
    module = build_module(args)
    written = await hist.collect(
        module.gamma,
        module.clob,
        start=hist.parse_day(args.start),
        end=hist.parse_day(args.end),
        path=args.out,
        min_volume=args.min_volume,
        tag_slug=args.tag,
        max_markets=args.max_markets,
        progress=out,
    )
    out(f"{written} markets appended to {args.out}")
    return 0


async def cmd_weather_history(args: argparse.Namespace, out: Printer) -> int:
    module = build_module(args)
    written = await wbt.collect_weather(
        module.gamma,
        module.clob,
        start=hist.parse_day(args.start),
        end=hist.parse_day(args.end),
        path=args.out,
        cities=args.city,
        max_pages=args.max_pages,
        concurrency=args.concurrency,
        batch=args.concurrency,
        progress=out,
    )
    out(f"{written} events appended to {args.out}")
    return 0


def _split(rows: Sequence[hist.HistoryRow], text: str | None) -> float:
    if text:
        return datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp()
    ends = sorted(r.end_time for r in rows)
    return ends[int(len(ends) * 0.7)] if ends else 0.0


async def cmd_calibrate(args: argparse.Namespace, out: Printer) -> int:
    rows = hist.load_rows(args.input)
    if not rows:
        out(f"no history in {args.input}: run `trading-polymarket history` first")
        return 1
    train, test = bt.split_rows(rows, _split(rows, args.split))
    if args.all:
        train, test = list(rows), []
    table = bt.calibrate(train, prior_strength=args.prior)
    out(f"trained on {len(train)} markets (test set: {len(test)})")
    out(f"{'price':>11} {'hours':>11} {'n':>6} {'mean':>6} {'won':>6} {'shrunk':>6}")
    for row in table.rows():
        out(
            f"{row['price_lo']:.2f}-{row['price_hi']:.2f} "
            f"{row['hours_lo']:>4g}-{row['hours_hi']:<6g} {row['n']:>6} "
            f"{row['mean_price']:6.3f} {row['win_rate']:6.3f} {row['shrunk']:6.3f}"
        )
    out(f"calibration written to {table.save(args.out)} (sha256 {table.sha256()[:12]})")
    return 0


async def cmd_backtest(args: argparse.Namespace, out: Printer) -> int:
    settings = PolymarketSettings.from_mapping(
        module_settings(getattr(args, "config", None))
    )
    if args.lane == "favourite":
        rows = hist.load_rows(args.input or hist.DEFAULT_HISTORY_PATH)
        if not rows:
            out("no history: run `trading-polymarket history` first")
            return 1
        train, test = bt.split_rows(rows, _split(rows, args.split))
        table = bt.calibrate(train)
        result = bt.backtest_favourite(
            test,
            table,
            settings.favourite,
            bankroll=settings.bankroll,
            half_spread=args.half_spread,
        )
    else:
        events = wbt.load_events(args.input or wbt.DEFAULT_WEATHER_HISTORY)
        if not events:
            out("no events: run `trading-polymarket weather-history` first")
            return 1
        module = build_module(args)
        oldest = min(e.day for e in events)
        today = datetime.fromtimestamp(module.clock(), UTC).date()
        past_days = min(92, (today - oldest).days + 2)
        forecasts = await wbt.day_ahead_forecasts(
            module.weather_client,
            load_stations(),
            [e.icao for e in events],
            models=settings.weather.models,
            past_days=past_days,
            progress=out,
        )
        observations = None
        if args.intraday:
            fetched = await wbt.station_metars(
                module.weather_client, [e.icao for e in events], progress=out
            )
            observations = metar_archive.merge(
                metar_archive.load_archive(args.metar_archive), fetched
            )
        result = wbt.backtest_weather(
            events,
            forecasts,
            settings.weather,
            bankroll=settings.bankroll,
            half_spread=args.half_spread,
            entry_hour=args.entry_hour,
            observations=observations,
        )
    path = _write(args.out or f"data/backtest/{args.lane}.jsonl", result.records)
    out(json.dumps(result.summary()))
    out(f"audit records written to {path}; judge them with:")
    out(
        f"  trading-core-audit verdict --path {path} "
        f"--rules configs/verdict/{args.lane}.json"
    )
    return 0


# -- parser -----------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-polymarket", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--config", help="trading-core config (its module_settings)")
        return p

    p = command("scan", "run the enabled lanes once and print the signals")
    p.add_argument("--lane", action="append", choices=LANES)
    p.add_argument("--limit", type=int, default=20)

    p = command("weather", "model vs market for open temperature events")
    p.add_argument("--city", action="append", default=[])

    p = command("record", "dry-run the lanes and log signals")
    p.add_argument("--lane", action="append", choices=LANES)
    p.add_argument("--cycles", type=int, default=1)
    p.add_argument("--interval", type=float, default=300.0)
    p.add_argument("--out", default=recorder.DEFAULT_RECORD_DIR)

    p = command("arb", "record-only arbitrage scan")
    p.add_argument("--pages", type=int, default=5)
    p.add_argument("--min-profit", type=float, default=0.005)
    p.add_argument("--min-size", type=float, default=5.0)
    p.add_argument("--out", default="data/arb.jsonl")

    p = command("bias", "measure weather-station forecast bias")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--station", action="append", default=[])
    p.add_argument("--out", default="data/weather_bias.json")

    p = command("metars", "append recent METARs to the archive (run daily)")
    p.add_argument("--out", default=metar_archive.DEFAULT_METAR_DIR)

    p = command("history", "collect resolved markets and price histories")
    p.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    p.add_argument("--end", required=True, help="YYYY-MM-DD (UTC, exclusive)")
    p.add_argument("--min-volume", type=float, default=1000.0)
    p.add_argument("--tag", default=None)
    p.add_argument("--max-markets", type=int, default=2000)
    p.add_argument("--out", default=hist.DEFAULT_HISTORY_PATH)

    p = command("weather-history", "collect resolved temperature events")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--max-pages", type=int, default=100)
    p.add_argument("--concurrency", type=int, default=8, help="requests in flight")
    p.add_argument("--city", action="append", default=[])
    p.add_argument("--out", default=wbt.DEFAULT_WEATHER_HISTORY)

    p = command("calibrate", "build the favourite calibration table")
    p.add_argument("--input", default=hist.DEFAULT_HISTORY_PATH)
    p.add_argument("--split", help="train on markets closing before this date")
    p.add_argument("--all", action="store_true", help="train on every market")
    p.add_argument("--prior", type=float, default=50.0)
    p.add_argument("--out", default="data/calibration.json")

    p = command("backtest", "replay a lane on collected history")
    p.add_argument("lane", choices=["favourite", "weather"])
    p.add_argument("--input")
    p.add_argument("--split", help="favourite: test on markets closing after this")
    p.add_argument("--half-spread", type=float, default=0.01)
    p.add_argument("--entry-hour", type=int, default=0, help="weather: local hour")
    p.add_argument(
        "--metar-archive",
        default=metar_archive.DEFAULT_METAR_DIR,
        help="weather --intraday: archived METARs to add (trading-polymarket metars)",
    )
    p.add_argument(
        "--intraday",
        action="store_true",
        help="weather: use METARs observed before the entry hour (last ~15 days)",
    )
    p.add_argument("--out")
    return parser


COMMANDS = {
    "scan": cmd_scan,
    "weather": cmd_weather,
    "record": cmd_record,
    "arb": cmd_arb,
    "bias": cmd_bias,
    "metars": cmd_metars,
    "history": cmd_history,
    "weather-history": cmd_weather_history,
    "calibrate": cmd_calibrate,
    "backtest": cmd_backtest,
}


def main(argv: Sequence[str] | None = None, *, out: Printer = print) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(COMMANDS[args.command](args, out))
    except BrokenPipeError:  # output piped into `head`: not an error
        return 0
    except (OSError, ValueError) as exc:
        out(f"error: {exc}")
        return 2


__all__ = ["COMMANDS", "build_parser", "main", "module_settings"]

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
