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
``updown-history`` collect crypto Up/Down markets: every trade, spot by second
``updown-backtest`` replay FEAT-146's or FEAT-147's rule on them
``ticks``          record Up/Down books, fills and spot to the millisecond
``ticks-report``   latency, stale asks and timestamp offset from a recording
``rewards-scan``   markets paying liquidity rewards, their terms, the competition
``weather-history``collect resolved temperature events + price histories
``fed-history``    collect settled Fed meetings on Polymarket and Kalshi
``calibrate``      build the favourite lane's calibration table
``backtest``       replay a lane on collected history (audit-format output)
``pairs``          suggest, approve and list cross-venue pairs
=================  ==========================================================

Every command is read-only towards Polymarket and Kalshi and uses free,
keyless APIs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from trading_polymarket import __version__
from trading_polymarket import pairs as pairs_mod
from trading_polymarket.clients.data_api import DataApiClient
from trading_polymarket.clients.http import HttpError, JsonHttp
from trading_polymarket.clients.spot import SpotClient
from trading_polymarket.config import LANES, PolymarketSettings
from trading_polymarket.module import PolymarketModule
from trading_polymarket.research import arb as arb_mod
from trading_polymarket.research import backtest as bt
from trading_polymarket.research import bias as bias_mod
from trading_polymarket.research import fed as fed_mod
from trading_polymarket.research import history as hist
from trading_polymarket.research import lane_rows as lane_mod
from trading_polymarket.research import metar_archive, recorder, updown
from trading_polymarket.research import pairs_suggest as suggest_mod
from trading_polymarket.research import rewards as rewards_mod
from trading_polymarket.research import ticks as ticks_mod
from trading_polymarket.research import ticks_report as treport
from trading_polymarket.research import updown_backtest as ubt
from trading_polymarket.research import updown_stale as ustale
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


async def cmd_updown_history(args: argparse.Namespace, out: Printer) -> int:
    module = build_module(args)
    result = await updown.collect(
        module.gamma,
        DataApiClient(module.http),
        SpotClient(module.http),
        asset=args.asset,
        window=args.window,
        start=updown.parse_day(args.start),
        end=updown.parse_day(args.end),
        directory=args.out,
        concurrency=args.concurrency,
        progress=out,
    )
    out(
        f"{result.days_written} days written ({result.markets} markets, "
        f"{result.trades} trades), {result.days_skipped} already in {args.out}"
        + (
            f"; not written: {', '.join(result.days_failed)}"
            if result.days_failed
            else ""
        )
    )
    return 1 if result.days_failed else 0


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:+.1f}%"


def _summary_line(summary: ubt.Summary, width: int) -> str:
    halves = " ".join(_percent(v) for v in summary.roi_halves)
    rate = "-" if summary.win_rate is None else f"{summary.win_rate * 100:.2f}%"
    price = "-" if summary.average_price is None else f"{summary.average_price:.4f}"
    p_value = "-" if summary.p_value is None else f"{summary.p_value:.3g}"
    return (
        f"{summary.rule.name:<{width}} {summary.entries:>6} {rate:>7} {price:>7} "
        f"{_percent(summary.roi):>7} {halves:>15} "
        f"{_percent(summary.roi_without_top):>8} {p_value:>8} "
        f"{'PASS' if summary.passed else 'fail'}"
    )


def _updown_replay(
    args: argparse.Namespace, markets: Iterable[updown.UpDownMarket]
) -> tuple[int, Sequence[Any], dict[Any, list[ubt.Entry]]]:
    """(markets read, the rules in order, entries by rule) for ``--rule``."""
    if args.rule == "stale":
        spot = ustale.SpotSeries(args.input, updown.SPOT_SYMBOLS[args.asset])
        count, stale = ustale.replay(
            markets,
            spot,
            ustale.GRID,
            offset=args.timestamp_offset,
            stake=args.stake,
        )
        return count, ustale.GRID, dict(stale)
    count, longshot = ubt.replay(markets, ubt.GRID, stake=args.stake)
    return count, ubt.GRID, dict(longshot)


def _updown_verdict(args: argparse.Namespace, by_rule: dict[Any, ubt.Summary]) -> str:
    if args.rule == "stale":
        return ustale.verdict(by_rule[ustale.PRIMARY], by_rule[ustale.STRESS])
    return "PASS" if by_rule[ubt.PRIMARY].passed else "FAIL"


async def cmd_updown_backtest(args: argparse.Namespace, out: Printer) -> int:
    start, end = updown.parse_day(args.start), updown.parse_day(args.end)
    split = start + (end - start) / 2
    markets = updown.load_markets(
        args.input, args.asset, args.window, start=start, end=end
    )
    count, rules, entries = _updown_replay(args, markets)
    if not count:
        out(f"no markets in {args.input}: run `trading-polymarket updown-history`")
        return 1
    width = max(len(r.name) for r in rules)
    out(f"{count} markets, {start} to {end} (second half from {split})")
    out(
        f"{'rule':<{width}} {'trades':>6} {'won':>7} {'price':>7} {'roi':>7} "
        f"{'halves':>15} {'-top1%':>8} {'p':>8}"
    )
    by_rule = {r: ubt.summarise(r, count, entries[r], split=split) for r in rules}
    for summary in by_rule.values():
        out(_summary_line(summary, width))
    primary = rules[0] if args.rule == "stale" else ubt.PRIMARY
    target = args.out or f"data/backtest/updown-{args.rule}.jsonl"
    path = _write(target, ubt.audit_records(entries[primary], primary))
    _write(
        str(Path(target).with_suffix(".summary.jsonl")),
        [s.to_dict() for s in by_rule.values()],
    )
    verdict = _updown_verdict(args, by_rule)
    out(f"primary ({primary.name}): {verdict}; its trades written to {path}")
    return 0


async def cmd_ticks(args: argparse.Namespace, out: Printer) -> int:
    module = build_module(args)
    counts = await ticks_mod.record(
        module.gamma,
        JsonHttp(transport=module.http.transport, max_retries=0),
        asset=args.asset,
        window=args.window,
        directory=args.out,
        hours=args.hours,
        spot_url=args.spot_url,
        log=lambda message: out(f"{datetime.now():%H:%M:%S} {message}"),
    )
    written = ", ".join(f"{n} {counts[n]}" for n in sorted(counts)) or "nothing"
    out(f"stopped; rows written: {written} (in {args.out})")
    return 0


def _quantile_line(label: str, found: dict[str, float] | None, digits: int = 0) -> str:
    if found is None:
        return f"{label}: none"
    p10, p50, p90 = (f"{found[k]:.{digits}f}" for k in ("p10", "p50", "p90"))
    return f"{label}: p10 {p10}, median {p50}, p90 {p90} (n {found['n']:.0f})"


async def _report_offsets(
    args: argparse.Namespace, recording: treport.Recording, out: Printer
) -> None:
    module = build_module(args)
    offsets = await treport.fetch_offsets(
        recording,
        DataApiClient(module.http),
        markets=args.offset_markets,
        now=module.clock(),
    )
    label = "data API time less the fill's WebSocket time (s)"
    out(_quantile_line(label, treport.quantiles(offsets), 2))
    middle = treport.median(offsets)
    if middle is not None:
        out(f"  updown-backtest --rule stale --timestamp-offset {middle:.2f}")


async def cmd_ticks_report(args: argparse.Namespace, out: Printer) -> int:
    start = updown.parse_day(args.start) if args.start else None
    end = updown.parse_day(args.end) if args.end else None
    recording = treport.load_recording(args.input, start=start, end=end)
    if not recording.days:
        out(f"no recording in {args.input}: run `trading-polymarket ticks`")
        return 1
    quotes = sum(len(q.rx) for q in recording.quotes.values())
    out(
        f"recorded {recording.days[0]} to {recording.days[-1]} "
        f"({len(recording.days)} days): {len(recording.spot)} spot, {quotes} quotes, "
        f"{len(recording.trades)} fills, {len(recording.probes)} probes"
    )
    delays = treport.quantiles(treport.receive_delays(recording))
    out(_quantile_line("Binance receive delay (ms, with any clock difference)", delays))
    rtts = treport.quantiles(treport.round_trips(recording))
    out(_quantile_line("round trip to the CLOB (ms)", rtts))
    if args.offset_markets:
        await _report_offsets(args, recording, out)
    found = treport.signals(recording)
    takeable = sum(s.takeable for s in found)
    censored = sum(s.censored for s in found)
    out(
        f"signals: {len(found)}; takeable {takeable}; "
        f"the ask outlived the window {censored}"
    )
    lifetimes = treport.quantiles([float(s.lifetime) for s in found])
    out(_quantile_line("  stale ask lifetime (ms)", lifetimes))
    ours = treport.quantiles([s.delay for s in found if s.delay is not None])
    out(_quantile_line("  our delay (ms)", ours))
    out(f"decision (FEAT-147 part 1): {treport.decision(len(recording.days), found)}")
    return 0


def _rewards_line(row: rewards_mod.Scan) -> str:
    mid = "-" if row.mid is None else f"{row.mid:.3f}"
    note = f" ({row.note})" if row.note else ""
    return (
        f"{row.reward_per_dollar:>8.4f} {row.reward_two_sided:>8.2f} "
        f"{row.daily_rate:>7.0f} {row.min_size:>5.0f} {row.max_spread_cents:>4.1f} "
        f"{mid:>6} {row.shares_bid:>8.0f} {row.shares_ask:>8.0f} "
        f"{(row.question or row.condition_id)[:60]}{note}"
    )


async def cmd_rewards_scan(args: argparse.Namespace, out: Printer) -> int:
    module = build_module(args)
    quote = rewards_mod.Quote(shares=args.quote_shares, cents=args.quote_cents)
    total, rows = await rewards_mod.scan(
        module.clob,
        module.gamma,
        limit=args.limit,
        min_daily_rate=args.min_daily_rate,
        quote=quote,
        now=module.clock(),
        progress=out,
    )
    path = rewards_mod.write_rows(
        rows, args.out or rewards_mod.default_out(module.clock())
    )
    out(
        f"{'$/day/$':>8} {'$/day':>8} {'pool':>7} {'min':>5} {'max':>4} "
        f"{'mid':>6} {'bid sh':>8} {'ask sh':>8} market"
    )
    for row in rows[: args.show]:
        out(_rewards_line(row))
    out(
        f"{len(rows)} of {total} rewarded markets written to {path}. One "
        "snapshot of each book, not a sampled day, and no adverse selection: "
        "it ranks where to look, not what a quote earns"
    )
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


async def cmd_fed_history(args: argparse.Namespace, out: Printer) -> int:
    module = build_module(args)
    written = await fed_mod.collect_fed(
        module.gamma,
        module.clob,
        module.kalshi,
        path=args.out,
        days=args.days,
        progress=out,
    )
    out(f"{written} meetings appended to {args.out}")
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
    elif args.lane == "fed":
        meetings = fed_mod.load_meetings(args.input or fed_mod.DEFAULT_FED_HISTORY)
        if not meetings:
            out("no meetings: run `trading-polymarket fed-history` first")
            return 1
        result = fed_mod.backtest_fed(
            meetings,
            settings.fed,
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


def _day(text: str | None) -> date | None:
    return None if text is None else date.fromisoformat(text)


async def cmd_lane_rows(args: argparse.Namespace, out: Printer) -> int:
    """Collected data as trading-core's strategy-library rows (FEAT-149)."""
    request = lane_mod.LaneRowsRequest(
        source=args.source,
        input=args.input,
        asset=args.asset,
        window=args.window,
        start=_day(args.start),
        end=_day(args.end),
        fee_rate=args.fee_rate,
        print_offset=args.print_offset,
    )
    stats = lane_mod.write_lane_rows(request, args.out)
    for line in lane_mod.describe(stats):
        out(line)
    out(f"rows written to {args.out}")
    return 0


async def cmd_pairs(args: argparse.Namespace, out: Printer) -> int:
    settings = PolymarketSettings.from_mapping(
        module_settings(getattr(args, "config", None))
    )
    path = args.pairs or settings.crossvenue.pairs_path
    if args.action == "suggest":
        module = build_module(args)
        pm, kalshi = await suggest_mod.gather(
            module.gamma,
            module.kalshi,
            pm_pages=args.pages,
            kalshi_pages=args.pages * 2,
        )
        found = suggest_mod.suggest(
            pm,
            kalshi,
            min_similarity=args.min_similarity,
            max_days_apart=args.max_days_apart,
        )
        written = _write(args.out, [s.to_dict() for s in found])
        out(f"{len(pm)} Polymarket and {len(kalshi)} Kalshi markets read")
        for s in found[: args.limit]:
            out(
                f"{s.score:.2f} {s.pm_question[:44]:<44} | "
                f"{s.kalshi_ticker} {s.kalshi_title[:40]}"
            )
        out(f"{len(found)} candidates written to {written}.")
        out("Check both venues' rules, then: pairs approve TOKEN TICKER")
        return 0
    pairs = pairs_mod.load_pairs(path)
    if args.action == "approve":
        if not args.token or not args.ticker:
            out("approve needs a Polymarket token and a Kalshi ticker")
            return 2
        pair = pairs_mod.VenuePair(
            pm_token=args.token,
            kalshi_ticker=args.ticker,
            kalshi_side=args.side,
            label=args.label or "",
        )
        written = pairs_mod.save_pairs([*pairs, pair], path)
        out(f"{len(pairs_mod.load_pairs(written))} pairs in {written}")
        return 0
    if args.action == "remove":
        kept = [p for p in pairs if p.pm_token != args.token]
        written = pairs_mod.save_pairs(kept, path)
        out(f"{len(pairs) - len(kept)} removed; {len(kept)} pairs in {written}")
        return 0
    for pair in pairs:
        token = f"{pair.pm_token[:12]}…"
        out(f"{token} {pair.kalshi_ticker} ({pair.kalshi_side}) {pair.label}")
    out(f"{len(pairs)} pairs in {path}")
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

    p = command("updown-history", "collect crypto Up/Down markets and their trades")
    p.add_argument("--asset", default="btc", choices=sorted(updown.SPOT_SYMBOLS))
    p.add_argument("--window", default="5m", choices=sorted(updown.WINDOWS))
    p.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    p.add_argument("--end", required=True, help="YYYY-MM-DD (UTC, exclusive)")
    p.add_argument("--concurrency", type=int, default=6, help="markets read at once")
    p.add_argument("--out", default=updown.DEFAULT_UPDOWN_DIR)

    p = command("updown-backtest", "replay the late-longshot rule (FEAT-146)")
    p.add_argument("--asset", default="btc", choices=sorted(updown.SPOT_SYMBOLS))
    p.add_argument("--window", default="5m", choices=sorted(updown.WINDOWS))
    p.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    p.add_argument("--end", required=True, help="YYYY-MM-DD (UTC, exclusive)")
    p.add_argument(
        "--rule",
        default="longshot",
        choices=["longshot", "stale"],
        help="longshot: FEAT-146; stale: FEAT-147 (cheap side after a spot move)",
    )
    p.add_argument(
        "--timestamp-offset",
        type=float,
        default=0.0,
        help="stale: seconds the data API's time runs after the fill (ticks-report)",
    )
    p.add_argument("--stake", type=float, default=ubt.STAKE, help="USDC an entry")
    p.add_argument("--input", default=updown.DEFAULT_UPDOWN_DIR)
    p.add_argument("--out", help="default data/backtest/updown-<rule>.jsonl")

    p = command("ticks", "record Up/Down books, fills and spot (FEAT-147)")
    p.add_argument("--asset", default="btc", choices=sorted(updown.SPOT_SYMBOLS))
    p.add_argument("--window", default="5m", choices=sorted(updown.WINDOWS))
    p.add_argument("--hours", type=float, help="stop after this long (default: Ctrl-C)")
    p.add_argument("--spot-url", help="Binance trade stream (default: the mirror)")
    p.add_argument("--out", default=ticks_mod.DEFAULT_TICKS_DIR)

    p = command("ticks-report", "latency, stale asks and timestamp offset (FEAT-147)")
    p.add_argument("--input", default=ticks_mod.DEFAULT_TICKS_DIR)
    p.add_argument("--start", help="YYYY-MM-DD (UTC; default: the first day)")
    p.add_argument("--end", help="YYYY-MM-DD (UTC, exclusive; default: all)")
    p.add_argument(
        "--offset-markets",
        type=int,
        default=20,
        help="markets to fetch from the data API for the timestamp offset (0: skip)",
    )

    p = command("rewards-scan", "markets paying liquidity rewards (FEAT-153)")
    p.add_argument(
        "--limit", type=int, default=rewards_mod.DEFAULT_LIMIT, help="best paid"
    )
    p.add_argument("--min-daily-rate", type=float, default=0.0, help="USD a day")
    p.add_argument(
        "--quote-shares",
        type=float,
        help="each side of the estimated quote (default: the market's minimum)",
    )
    p.add_argument("--quote-cents", type=float, default=1.0, help="from the midpoint")
    p.add_argument("--show", type=int, default=30, help="rows printed")
    p.add_argument("--out", help="default data/rewards/rewards-<UTC time>.jsonl")

    p = command("weather-history", "collect resolved temperature events")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--max-pages", type=int, default=100)
    p.add_argument("--concurrency", type=int, default=8, help="requests in flight")
    p.add_argument("--city", action="append", default=[])
    p.add_argument("--out", default=wbt.DEFAULT_WEATHER_HISTORY)

    p = command("fed-history", "collect settled Fed meetings on both venues")
    p.add_argument("--days", type=float, default=14.0, help="history before each close")
    p.add_argument("--out", default=fed_mod.DEFAULT_FED_HISTORY)

    p = command("calibrate", "build the favourite calibration table")
    p.add_argument("--input", default=hist.DEFAULT_HISTORY_PATH)
    p.add_argument("--split", help="train on markets closing before this date")
    p.add_argument("--all", action="store_true", help="train on every market")
    p.add_argument("--prior", type=float, default=50.0)
    p.add_argument("--out", default="data/calibration.json")

    p = command("backtest", "replay a lane on collected history")
    p.add_argument("lane", choices=["favourite", "weather", "fed"])
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

    p = command("pairs", "suggest, approve, remove and list cross-venue pairs")
    p.add_argument("action", choices=["suggest", "approve", "remove", "list"])
    p.add_argument("token", nargs="?", help="approve/remove: Polymarket token id")
    p.add_argument("ticker", nargs="?", help="approve: Kalshi market ticker")
    p.add_argument("--side", choices=["yes", "no"], default="yes")
    p.add_argument("--label")
    p.add_argument("--pairs", help="pairs file (default: crossvenue.pairs_path)")
    p.add_argument("--pages", type=int, default=5, help="suggest: Gamma pages read")
    p.add_argument("--min-similarity", type=float, default=0.5)
    p.add_argument("--max-days-apart", type=float, default=3.0)
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--out", default=suggest_mod.DEFAULT_SUGGESTIONS)
    p = command("lane-rows", "collected data as strategy-library rows (FEAT-149)")
    p.add_argument("--from", dest="source", required=True, choices=lane_mod.SOURCES)
    p.add_argument(
        "--input",
        required=True,
        help="the collected file (history, weather-history, fed-history) or, for "
        "updown-history, its folder",
    )
    p.add_argument("--out", required=True, help="a new .jsonl or .jsonl.gz file")
    p.add_argument("--asset", default="btc", choices=sorted(updown.SPOT_SYMBOLS))
    p.add_argument("--window", default="5m", choices=sorted(updown.WINDOWS))
    p.add_argument("--start", default=None, help="updown days from YYYY-MM-DD")
    p.add_argument("--end", default=None, help="updown days before YYYY-MM-DD")
    p.add_argument(
        "--fee-rate",
        type=float,
        default=None,
        help="keep only markets at this taker fee rate (one sweep, one rate)",
    )
    p.add_argument(
        "--print-offset",
        type=float,
        default=0.0,
        help="seconds added to every updown trade print (FEAT-147's offset)",
    )
    return parser


COMMANDS = {
    "scan": cmd_scan,
    "weather": cmd_weather,
    "record": cmd_record,
    "arb": cmd_arb,
    "bias": cmd_bias,
    "metars": cmd_metars,
    "history": cmd_history,
    "updown-history": cmd_updown_history,
    "updown-backtest": cmd_updown_backtest,
    "ticks": cmd_ticks,
    "ticks-report": cmd_ticks_report,
    "rewards-scan": cmd_rewards_scan,
    "weather-history": cmd_weather_history,
    "calibrate": cmd_calibrate,
    "fed-history": cmd_fed_history,
    "backtest": cmd_backtest,
    "pairs": cmd_pairs,
    "lane-rows": cmd_lane_rows,
}


def main(argv: Sequence[str] | None = None, *, out: Printer = print) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(COMMANDS[args.command](args, out))
    except BrokenPipeError:  # output piped into `head`: not an error
        return 0
    except KeyboardInterrupt:  # Ctrl-C ends `ticks`; files are closed on the way
        out("stopped")
        return 130
    except (OSError, ValueError, HttpError) as exc:
        out(f"error: {exc}")
        return 2


__all__ = ["COMMANDS", "build_parser", "main", "module_settings"]

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
