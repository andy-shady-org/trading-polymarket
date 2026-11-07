# Done

Finished work from 2026-10-31; earlier work is in
[`CHANGELOG.md`](../../CHANGELOG.md). Items move here from
[`TODO.md`](TODO.md) under the heading they had there, with the release
they shipped in. This file is appended to, never edited back.

## Evidence (before the paper pilot)

- [x] Start the 0.2.1 pilots (weather, fed) after the smoke run and the
      restart drill ([`releases/0.2.1.md`](releases/0.2.1.md)); `metars` in
      cron. *(v0.2.1; started as the runs `weather-0.2.1` and `fed-0.2.1`,
      [`RELEASE-GATE.md` §1](RELEASE-GATE.md#1-current-status). Moved here
      2026-10-31. Recording the smoke run's and the drill's results is open
      in [`TODO.md`](TODO.md).)*

## Docs

- [x] Docs follow trading-core's `docs/dev/DOCUMENTATION.md`: the standard
      layout, pages and records (2026-10-31, Unreleased; `CHANGELOG.md`
      Docs).

## Next: trading-core 0.7.0 (2026-11-04, 0.3.0)

- [x] **`v0.3.0` on trading-core `v0.7.0`, with trusted loading (trading-core 0.3.0, FEAT-89 / FEAT-90; this repository is under its Needed by):** `v0.3.0` declares `trading-core>=0.3.0,<0.8` (`<0.6` on `main` since 2026-11-03) and is tagged with `git tag -s`; `runtime-trading` has a `modules.toml` (written 2026-10-31) and needs `allowed_signers` with the signing key (trading-core's `SECURITY.md`, "Signed releases"). Its `bin/install-release.sh` already refuses an unsigned tag (`ALLOW_UNSIGNED=1` for the old ones). *(the code part, on `release/v0.3.0`; tested on trading-core `v0.7.0`; the tag and `allowed_signers` are the release's, in `TODO.md`)*

## Up/Down research (2026-11-04, 0.4.0)

- [x] **FEAT-146** ([`DONE.md`](DONE.md#feat-146-updown-trade-backfill-and-late-longshot-backtest)): `updown-history` collected every taker trade of 8,615 BTC 5-minute markets (2026-10-05 to 11-03); `updown-backtest` ran the pre-registered late-longshot rule on them: **NO-GO** (−16.9% on stake over 4,500 entries; [`RESULTS.md`](RESULTS.md)). Recorded in trading-core's master ledger and lessons.

## Runs (2026-11-04)

- [x] **`weather-0.2.1` and `fed-0.2.1` closed** (stopped 2026-11-03 05:57 UTC; closed early, not judged: 16 and 2 positions; [`releases/0.2.1.md`](releases/0.2.1.md#read-out)). Their 0.2.1 smoke run and drill were never recorded. Replaced by `weather-1` and `fed-1` on `v0.4.0`, pre-registered with the same lane settings ([`runs/README.md`](runs/README.md)).

## Built proposals moved from PROPOSED-FEATURES.md (2026-11-07)

Proposals whose work is done, moved whole and unedited from [`PROPOSED-FEATURES.md`](PROPOSED-FEATURES.md) on 2026-11-07 (headings one level down): FEAT-103 (built, Unreleased; NO-GO 2026-11-07), FEAT-146 (`v0.4.0`; NO-GO 2026-11-04), FEAT-149 and FEAT-153 (built, Unreleased). What ships is in [`../FEATURES.md`](../FEATURES.md); the results in [`RESULTS.md`](RESULTS.md).

#### FEAT-103: Expiry-fade backtest
* **Class / Priority:** Research · P3
* **Goal:** test one more taker rule cheaply before anyone builds it: in the last 1–5 minutes of an Up/Down market, with spot flat (a move under 0.06% recently), buy the cheaper side when the price is at least 15 c from 0.50 (CloddsBot's "expiry fade").
* **Prior:** low. A favourite–longshot bias would make the cheap side overpriced, not underpriced, and the study found Polymarket's mid more accurate than a spot model.
* **Design:** a research command on the settled-market history (about 20,000 markets in six weeks; minute prices and `priceToBeat` / `finalPrice` from Gamma), buying at the next print after the signal plus the taker fee `0.07 × p(1 − p)`; the mirror rule (buy the favourite) beside it. Minute data overstated a taker edge once (the crypto-updown artefact), so a positive result must be confirmed on FEAT-101's ticks before anything else.
* **Stop rule:** negative after fees on the minute data ends it.
* **Dependencies:** the history collection; FEAT-101 for confirmation. **Impact:** about an hour to close a question.
* **Pre-registered here, 2026-11-07, before any run** (built as `updown-backtest --rule fade`, `research/updown_fade.py`):
  - **Data:** the FEAT-146 backfill, BTC 5-minute markets of 2026-10-05 to 2026-11-03 (30 days), every taker trade to the second and Binance's one-second spot; halves split at the middle day, as FEAT-146's. Not minute prices: the backfill is finer, so the minute-data caution applies less, and the ticks confirmation still applies.
  - **Signal:** the first second `τ` with 300 to 60 seconds of the window left (for a 5-minute window: 60 s to 240 s in, the spot test needs 60 s of spot) at which spot moved less than 6 bp (0.06%) over the 60 seconds before, and one outcome's last print is 0.35 or less (the fade buys it) or, for the mirror, 0.65 or more (it buys that). With both past it, the further one.
  - **Fill:** the first buy print of that outcome in a later second, within 5 s (0 s latency; 3 s in the stress rule), at most 1 c above the price seen, with at least the $5 stake's notional, at its price; settlement at 1 or 0, the taker fee `0.07 × p(1 − p)` a share on the entry.
  - **Verdict, primary rule (the fade at 15 c):** FEAT-147's bar: PASS when return on stake is above zero in both halves and without the best 1% of markets, the win rate is above the average fill price at binomial p < 0.05, and the stress rule does not lose; INCONCLUSIVE below 200 entries; FAIL otherwise. The mirror, 10 c and 25 c, and no spot filter are reported, not judged.
  - **What follows:** FAIL closes FEAT-103 (the stop rule); PASS is confirmed on FEAT-101's ticks before anything else.
  - **Result (2026-11-07): FAIL, NO-GO.** −8.0% on stake over 6,139 trades, both halves negative; every variant and the mirror lose. FEAT-103 is closed ([`RESULTS.md`](RESULTS.md)).

#### FEAT-146: Up/Down trade backfill and late-longshot backtest
* **Class / Priority:** Research · P2 · added 2026-11-04.
* **Goal:** find out whether buying the cheap side of a 5-minute BTC Up/Down market late in its window earns after fees, on every market rather than one wallet's picks.
* **Why:** the wallet `@vega7` (0x6ba2…8d0e) made +$33.7K on $81.8K over 10,363 of these markets (2026-04-19 to 2026-11-04, its public activity). Almost all of it came from buys under 5 c in the last two minutes (+$29.2K on 2,300 markets, 4% of them won) and it sold near-certain winners at 0.96–0.98 before the close. The result is fat-tailed: without its 50 best markets it is −$15.5K. It bought both sides in only 4.5% of markets.
* **Built (part 1, 0.4.0):** `trading-polymarket updown-history` (`research/updown.py`, `docs/CLI.md`): every settled market of an asset and window, a day at a time, with every taker trade to the second, the outcome and Chainlink's start and end prices, and one-second Binance spot. A 5-minute BTC day is about 1,600 trades a market, 7.7 MB gzipped, three minutes to read.
* **Part 2, the backtest (pre-registered here, 2026-11-04, before any run):**
  - **Data:** BTC 5-minute markets of 2026-10-05 to 2026-11-03 (30 days, about 8,640 markets).
  - **Rule:** in each market, the first `BUY` print of an outcome at or below `cap` at or after `from` seconds into the window is the signal; the entry fills at the next `BUY` print of that outcome in a later second, at that print's price, if the print is at least the stake ($5) and its price is at most `cap` + 1 c; otherwise the next such print. One entry a market, held to settlement. Taker fee `0.07 × p(1 − p)` a share.
  - **Primary variant:** `cap` 5 c, `from` 240 s. Descriptive only: `cap` in {2, 5, 10} c × `from` in {180, 240, 270} s, and the same rule with `from` 0 and entries before 180 s (is late better than early at the same price?).
  - **Pass bar (primary variant):** return on stake after fees above zero in both halves (15 days each); above zero with the best 1% of markets by profit removed; and a win rate above the average fill price with one-sided binomial p < 0.05.
  - **Then:** a pass is confirmed on FEAT-101's ticks (the book, not only prints) before any lane; a fail is recorded as NO-GO in `docs/STRATEGY-LEDGER.md`. Selling winners at 0.96–0.98 is a separate question, not part of this test.
* **Dependencies:** none. **Impact:** closes the question in a day; shares the backfill with FEAT-103, which can now use second-level prints instead of minute prices.
* **Built (part 2, 0.4.0):** `trading-polymarket updown-backtest` (`research/updown_backtest.py`).
* **Result (2026-11-04): NO-GO.** The primary rule lost $3,802.34 on 4,500 entries (−16.9% on stake; halves −26.9% and −7.8%; −84.5% without the best 1%); it won 2.07% at an average fill of 2.23 c (p = 0.78). Every descriptive variant lost. Run on the pre-registered data and rule without change; prints after a window's close are not used. Details: [`RESULTS.md`](RESULTS.md).

#### FEAT-149: Library rows from Polymarket's data (`lane-rows`)
* **Class / Priority:** Research tooling · P3 · added 2026-11-04. **Built (Unreleased), 2026-11-07:** `research/lane_rows.py`, `trading-polymarket lane-rows` (CLI §2.4, RESEARCH §4d), with trading-core's `--price-fee-rate` (trading-core FEAT-149's core part, Unreleased). Every outcome token is its own instrument; `--fee-rate` keeps one category's rate; `ticks` rows (`Quote`, trading-core FEAT-148) are still to come.
* **Goal:** run trading-core's venue sweep (`trading-core-lanes sweep`) over Polymarket's history with the library's outcome-market rules, `reference_gap` (FEAT-137) and `probability_band` (FEAT-138), the way trading-pump, trading-evm and trading-meteora feed theirs.
* **Design:** `trading-polymarket lane-rows --input <collected file or folder> --out rows.jsonl.gz` writes the library's JSON rows from data already collected:
  - `history` and `weather-history`: a `Listing` per market (with `resolves_at`), a `Reading` per price point, an `Outcome` at settlement;
  - `fed-history`: the same, with Kalshi's price as each reading's `reference`;
  - `updown-history`: a `Listing` per window (`resolves_at` its end), a `Reading` and a `TradePrint` per taker trade (the data API names the taker's wallet), an `Outcome`; print times corrected by the data API's offset (FEAT-147);
  - later, `ticks`: `Quote` rows for trading-core FEAT-148.
* **Needs in trading-core:** a taker fee that depends on the price in the sweep (Polymarket charges `rate × p(1 − p)` a share, by category), where the sweep now takes flat basis points. That small core change is part of this feature.
* **Caution:** the sweep only shortlists; the favourite–longshot and day-ahead weather results it would revisit are NO-GO already (`STRATEGY-LEDGER.md` §3.5), and a shortlist is judged only by a pre-registered run on fresh data.
* **Dependencies:** trading-core's library (built, `v0.6.0`); the price-dependent fee. **Impact:** Polymarket joins "test a venue against every strategy".

#### FEAT-153: Liquidity-rewards scan (`rewards-scan`)
* **Class / Priority:** Research tooling · P2 · added 2026-11-04 (the November roadmap, item 3.3). **Built (Unreleased).**
* **Goal:** find the markets where a small maker could earn Polymarket's liquidity rewards: what each pays, on what terms, and how much resting liquidity already competes for it.
* **Built:** `trading-polymarket rewards-scan` (`research/rewards.py`, `docs/CLI.md`, `docs/RESEARCH.md` §4c): every rewarded market from CLOB `/rewards/markets/current`, the best paid ones' details (Gamma, by condition id) and books, the shares inside each reward spread, and a two-sided quote's estimated share of the pool under Polymarket's scoring (one snapshot; see the module docstring for what it ignores). Markets past their end date and books wider than twice the reward spread rank last.
* **First scan (2026-11-04):** 14,554 rewarded markets paying about $234,000 a day (median $5, p90 $32; 223 pay $100 or more). Of the 300 best paid, 107 had ended (awaiting results) and 51 had wide books. The 182 clean books held a median of about 10,000–12,500 shares inside the spread on each side; the snapshot estimates (median 4.5% a day of the quote's capital) are far too high to trust as earnings, because a thin book at one moment is not a day.
* **Then:** pick a handful of clean, quiet markets and record their books for a day with `ticks`-style sampling (FEAT-101's maker study measures what a quote loses to adverse selection there); only a phase or market that earns after that becomes trading-core FEAT-148's first family.
* **Dependencies:** none. **Impact:** points the maker study at the seat Polymarket subsidises.
