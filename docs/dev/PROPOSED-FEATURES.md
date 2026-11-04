# Proposed features

Features of trading-polymarket that are not built, and why. What is
built is in [`../FEATURES.md`](../FEATURES.md); open work on what exists is
in [`TODO.md`](TODO.md).

**IDs.** `FEAT-<n>` is one series shared by every repository, kept in
trading-core's `docs/dev/PROPOSED-FEATURES.md`: take the next free number
there and bump it in the same pull request. The ideas in §1 were written
before that series reached this repository and **have no ID yet**; give one
an ID when work on it starts. §2 has the proposals that took IDs.

A feature that needs another repository's work takes its own ID here and
names the other part under **Needs** or **Needed by**, with that
repository and the release that delivers it (trading-core's
`docs/dev/DOCUMENTATION.md` §9).

## 1. Ideas not built (and why)

Moved here on 2026-10-31 from `docs/STRATEGIES.md`, unchanged.

- **Market making / liquidity rewards** (`polymarket_lp_tool`): needs resting
  orders and live signing; revisit after live execution. The research half is now FEAT-101 (§2): measure where a maker earns before building order placement.
- **LLM news analyst** (TradingAgents, AutoPilotPM): costs per call and no
  measured edge; the momentum lane's metrics must first show attention matters.
- **Two-legged cross-venue arbitrage** (buy on one venue, sell on the
  other): needs a Kalshi account and order signing; the `fed` and
  `crossvenue` lanes use Kalshi as a reference price only.

## 2. Proposed with an ID (2026-10-31)

From the review of the CloddsBot repository (an open-source TypeScript bot
with Polymarket and Solana strategies; project doc
`claude/cloddsbot-review-2026-10-31.md`), checked against what this
project's own studies found (project docs `claude/crypto-updown-2026-10-30.md`
and `claude/sports-cross-venue-2026-10-30.md`). Its main Polymarket idea,
buying the 15-minute Up/Down side after a fast spot move, is the latency
arbitrage the crypto-updown study showed to be an artefact of minute data,
and is not proposed. The three below are research first: record-only, no
orders.

| ID | Feature | Kind | Why |
|---|---|---|---|
| FEAT-101 | Up/Down tick recorder and maker study | Research, then a lane | The professional seat in these markets is the maker's (rebates, rewards); find the phases where makers earn |
| FEAT-102 | Full-set scanner: both sides, depth, duration, loop | Research, then an executor | `arb` exists but has never been run; measure whether full-set gaps are frequent, large and lasting |
| FEAT-103 | Expiry-fade backtest | Research | A cheap test of one more taker rule; low prior |
| FEAT-146 | Up/Down trade backfill and late-longshot backtest | Research | A profitable wallet's pattern, testable on every trade of past markets without waiting for a recorder. Built (0.4.0); the backtest is **NO-GO** (2026-11-04, [`RESULTS.md`](RESULTS.md)) |
| FEAT-147 | Up/Down stale quotes after a spot move | Research, then a lane | Second-level prints show a 2–5 s edge after a Binance move, the edge the bot `@vega7` appears to trade; takeable only if we are fast enough |
| FEAT-149 | Library rows from Polymarket's data (`lane-rows`) | Research tooling | Sweep trading-core's outcome-market rules (`reference_gap`, `probability_band`) over the history already collected. Not built |
| FEAT-153 | Liquidity-rewards scan (`rewards-scan`) | Research tooling | Which markets pay makers to quote, on what terms and against how much competition: the subsidised maker seat. Built (Unreleased) |

### FEAT-101: Up/Down tick recorder and maker study
* **Class / Priority:** Income (research) · P2
* **Goal:** find out whether a maker can earn on the crypto Up/Down markets, and when. The crypto-updown study (45 minutes of ticks, 18,678 trades) found makers at about break-even before the 20% fee rebate (−0.41 c a share on 5-minute markets, −0.07 c on 15-minute ones) and, noisily, earning in the last minute (+3.7 c at 30–60 s left on 5-minute markets) and losing at 2–5 minutes left (−1.5 c). That needs 24–48 h of ticks to say with any confidence.
* **Design:**
  - `trading-polymarket ticks`: a research command, record-only, run in tmux on the Mac. Subscribes to a spot ticker (Coinbase, which matched settlement 93–99% of the time on minute data) and to Polymarket's market WebSocket (best bid and ask, book depth near the top, trades) for the open Up/Down markets of chosen assets and windows; writes daily JSONL under `data/ticks/`. The scratchpad prototypes from 2026-10-30 (`recorder.py`, `ticks_analyze.py`, `maker.py`) are the starting point, rewritten to this repository's standard with tests.
  - `trading-polymarket ticks-report`: per market and phase (time to expiry), maker P&L per share against settlement, before and after the rebate; adverse selection (the mid one, five and thirty seconds after each fill); spot moves before fills; book imbalance `(bid depth − ask depth) / (bid depth + ask depth)` at each fill.
  - **The maker study:** a simulated quote at the best bid or ask, counted as filled only when a trade prints **through** its price (never on a touch, so queue position cannot flatter it), with two pull rules taken from CloddsBot's crypto strategies and tested here: pull on a spot move above a threshold, and shorten or pull when book imbalance turns against the quote. Phases kept only where the simulated maker earns in both halves of the recording.
* **Then:** if a phase earns after adverse selection on two separate recordings, a maker lane needs live order placement (`LiveExecutor`, `LIVE-TRADING.md`), which paper cannot judge honestly (the sports study's note); it would start at Stage 2 with a tiny size, not as a paper pilot.
* **Dependencies:** none for the recorder; live execution for a lane. **Impact:** the only seat in these markets the studies so far leave open.
* **Recorder built (0.4.0) as `ticks`** (FEAT-147): best bid and ask, fills and spot to the millisecond. The maker study (`ticks-report` per phase, the simulated quote) is not built; its first read is scheduled for 2026-11-05 on the Mac's recording.
* **Then, for every venue:** a phase that earns becomes the first family of trading-core FEAT-148 (order-book records, a resting-order simulator, maker and liquidity-provider rules in the strategy library).

### FEAT-102: Full-set scanner: both sides, depth, duration, loop
* **Class / Priority:** Income (research) · P2
* **Goal:** measure, over a week, whether buying a complete set of outcomes for less than it pays is a real opportunity. Saguillo et al., "Unravelling the probabilistic forest: arbitrage in prediction markets" (arXiv 2508.03474), found such gaps were taken on Polymarket at scale; CloddsBot's version checks mid prices and binary Yes + No pairs, which on Polymarket are one mirrored book. `trading-polymarket arb` (`research/arb.py`) already checks binary pairs and neg-risk Yes sets at the best asks, but it has never been run (no `data/arb.jsonl` in `runtimes/polymarket`).
* **Design:**
  - **The No side:** in an n-outcome neg-risk event, buying every No pays n − 1; record when the No asks sum, fees included, to less than that.
  - **Depth:** walk each leg's book to find the cost for 10, 50 and 100 sets and the largest size that still clears the threshold, not only the best level.
  - **Duration:** a gap seen is re-checked every few seconds until it closes; record its lifetime.
  - **Loop mode:** `arb --loop --interval 30` for a long run in tmux or cron, with a daily summary (`arb-report`: count, size, profit and lifetime by event category, augmented events apart).
  - Fees per market from its fee schedule (most non-sports, non-crypto markets have none).
* **Decision rule (written before the week starts):** an executor is worth building only if, after fees, there are at least 10 gaps a day of at least $5 each at a fillable size, lasting at least 10 s. trading-core opens one instrument per signal, so an executor needs multi-leg orders, a core change of its own.
* **Dependencies:** none. **Impact:** risk-free when filled; the question is only whether anything is left after the bots that already take these.

### FEAT-103: Expiry-fade backtest
* **Class / Priority:** Research · P3
* **Goal:** test one more taker rule cheaply before anyone builds it: in the last 1–5 minutes of an Up/Down market, with spot flat (a move under 0.06% recently), buy the cheaper side when the price is at least 15 c from 0.50 (CloddsBot's "expiry fade").
* **Prior:** low. A favourite–longshot bias would make the cheap side overpriced, not underpriced, and the study found Polymarket's mid more accurate than a spot model.
* **Design:** a research command on the settled-market history (about 20,000 markets in six weeks; minute prices and `priceToBeat` / `finalPrice` from Gamma), buying at the next print after the signal plus the taker fee `0.07 × p(1 − p)`; the mirror rule (buy the favourite) beside it. Minute data overstated a taker edge once (the crypto-updown artefact), so a positive result must be confirmed on FEAT-101's ticks before anything else.
* **Stop rule:** negative after fees on the minute data ends it.
* **Dependencies:** the history collection; FEAT-101 for confirmation. **Impact:** about an hour to close a question.

### FEAT-146: Up/Down trade backfill and late-longshot backtest
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

### FEAT-147: Up/Down stale quotes after a spot move
* **Class / Priority:** Research, then a lane · P1 · added 2026-11-04.
* **Goal:** find out whether we can buy the cheap side of a BTC 5-minute Up/Down market in the seconds after Binance moves in its favour, before makers reprice, and whether that earns after fees.
* **Why:** a study on FEAT-146's backfill (2026-11-04, [`RESULTS.md`](RESULTS.md); in-sample, descriptive). In the last minute, cheap buys (≤ 5 c) with Binance spot at or past the start price toward the bought side returned **+163%** on stake when spot is read 2 s before the print, and **−30%** when it is read 5 s before; every cell loses with spot 5 s old. The wallet `@vega7`, a Claude bot, won 22 of 540 cheap buys where 5-second-old spot predicts 11. This reopens the ledger's "latency trades" entry, which minute data had closed.
* **Part 1, the recorder (first; decides whether we could take it at all):** `trading-polymarket ticks` (shared with FEAT-101), record-only, on the Mac. It subscribes to Binance's BTCUSDT trade stream (or its market-data mirror) and Polymarket's market WebSocket for the open BTC 5-minute markets (best bid and ask, depth near the top, trades), and writes daily JSONL with local receive times in milliseconds. It measures:
  - **the timestamp offset:** the data API's trade `timestamp` against the moment the same trade appears on the market WebSocket (the CLOB matches off chain and settles on Polygon; which time the data API reports is not known);
  - **how long a stale ask lives:** for each signal of the rule below, the time from the Binance trade that met the condition until the side's best ask at or below `cap` + 1 c is gone or repriced;
  - **our own latency:** Binance's event time against our receive time, plus a round trip to the CLOB's host.

  **Decision:** the lead is takeable only if, in at least half of the signals over at least three days of recording, the stale ask lives longer than our receive delay plus one round trip. If not, FEAT-147 stops there: NO-GO for us, whatever the backtest says.
* **Part 2, the rule (pre-registered here, 2026-11-04, before any data it is judged on exists):**
  - **Data:** a fresh window, BTC 5-minute markets of **2026-11-04 to 2026-11-17** (14 days), collected with `updown-history` after the 17th. The study's 30 days found the rule and are not used to judge it.
  - **Signal:** at the first second `τ` in [240, 300) of a window at which, for an outcome `o`, the Binance one-second close at `τ` is at or past −1.5 bp from the window's first Binance close in `o`'s favour, and `o`'s last print at or before `τ` was at or below `cap` = 5 c.
  - **Fill:** the first `BUY` print of `o` at or below `cap` + 1 c with notional at least the stake ($5), timestamped in [`τ + L`, `τ + L + 5`] s, at that print's price; none in that interval, no entry. `L` = 2 s, after correcting the data API's timestamp by the median offset part 1 measured. One entry a market, held to settlement, taker fee `0.07 × p(1 − p)` a share; prints after the window's close are never used.
  - **Pass bar:** return on stake after fees above zero in each 7-day half; above zero with the best 1% of markets removed; win rate above the average fill price at one-sided binomial p < 0.05; not negative at `L` = 3 s (the stress cost); at least 200 entries, or the verdict is INCONCLUSIVE.
  - **Descriptive only:** `L` in {1, 2, 3, 5} s; `cap` in {3, 5, 10} c; the spot threshold at −4, −1.5 and 0 bp; signals from 120 s instead of 240 s.
* **Then:** a pass on both parts is still a print replay: whether our order gets the ask is a race paper cannot judge. A lane would start at Stage 2 (live canary, the smallest size) once live execution is built (`LIVE-TRADING.md`). A fail is recorded as NO-GO in `docs/STRATEGY-LEDGER.md`.
* **Dependencies:** FEAT-101's recorder (part 1 builds it); FEAT-146's collector and backtest (part 2 extends `updown-backtest`). **Impact:** the first lead with a mechanism (stale quotes) and a winner who trades it; also says whether our setup can compete on speed at all.
* **Built (0.4.0):** part 1, `trading-polymarket ticks` and `ticks-report` (`research/ticks.py`, `research/ticks_report.py`); part 2, `updown-backtest --rule stale` (`research/updown_stale.py`). Two readings the rule's text left open, fixed in the code before any data it is judged on exists: spot "at `τ`" is the one-second candle that ended at `τ` (opened at `τ − 1`), and the start price is the candle that ended at the window's start. The recorder's signal uses the live best ask at or below `cap` + 1 c where the backtest uses the last print.
* **First measurement (2026-11-04, 6 minutes): the data API's times run a median 2.2 s after the fill.** The study's lags were in that time, so the edge after a spot move is under a second, and the rule with the offset loses even in-sample (−4.3%; [`RESULTS.md`](RESULTS.md)). Part 1 now decides it: whether stale asks outlive our delay.

### FEAT-149: Library rows from Polymarket's data (`lane-rows`)
* **Class / Priority:** Research tooling · P3 · added 2026-11-04. **Not built.**
* **Goal:** run trading-core's venue sweep (`trading-core-lanes sweep`) over Polymarket's history with the library's outcome-market rules, `reference_gap` (FEAT-137) and `probability_band` (FEAT-138), the way trading-pump, trading-evm and trading-meteora feed theirs.
* **Design:** `trading-polymarket lane-rows --input <collected file or folder> --out rows.jsonl.gz` writes the library's JSON rows from data already collected:
  - `history` and `weather-history`: a `Listing` per market (with `resolves_at`), a `Reading` per price point, an `Outcome` at settlement;
  - `fed-history`: the same, with Kalshi's price as each reading's `reference`;
  - `updown-history`: a `Listing` per window (`resolves_at` its end), a `Reading` and a `TradePrint` per taker trade (the data API names the taker's wallet), an `Outcome`; print times corrected by the data API's offset (FEAT-147);
  - later, `ticks`: `Quote` rows for trading-core FEAT-148.
* **Needs in trading-core:** a taker fee that depends on the price in the sweep (Polymarket charges `rate × p(1 − p)` a share, by category), where the sweep now takes flat basis points. That small core change is part of this feature.
* **Caution:** the sweep only shortlists; the favourite–longshot and day-ahead weather results it would revisit are NO-GO already (`STRATEGY-LEDGER.md` §3.5), and a shortlist is judged only by a pre-registered run on fresh data.
* **Dependencies:** trading-core's library (built, `v0.6.0`); the price-dependent fee. **Impact:** Polymarket joins "test a venue against every strategy".

### FEAT-153: Liquidity-rewards scan (`rewards-scan`)
* **Class / Priority:** Research tooling · P2 · added 2026-11-04 (the November roadmap, item 3.3). **Built (Unreleased).**
* **Goal:** find the markets where a small maker could earn Polymarket's liquidity rewards: what each pays, on what terms, and how much resting liquidity already competes for it.
* **Built:** `trading-polymarket rewards-scan` (`research/rewards.py`, `docs/CLI.md`, `docs/RESEARCH.md` §4c): every rewarded market from CLOB `/rewards/markets/current`, the best paid ones' details (Gamma, by condition id) and books, the shares inside each reward spread, and a two-sided quote's estimated share of the pool under Polymarket's scoring (one snapshot; see the module docstring for what it ignores). Markets past their end date and books wider than twice the reward spread rank last.
* **First scan (2026-11-04):** 14,554 rewarded markets paying about $234,000 a day (median $5, p90 $32; 223 pay $100 or more). Of the 300 best paid, 107 had ended (awaiting results) and 51 had wide books. The 182 clean books held a median of about 10,000–12,500 shares inside the spread on each side; the snapshot estimates (median 4.5% a day of the quote's capital) are far too high to trust as earnings, because a thin book at one moment is not a day.
* **Then:** pick a handful of clean, quiet markets and record their books for a day with `ticks`-style sampling (FEAT-101's maker study measures what a quote loses to adverse selection there); only a phase or market that earns after that becomes trading-core FEAT-148's first family.
* **Dependencies:** none. **Impact:** points the maker study at the seat Polymarket subsidises.

