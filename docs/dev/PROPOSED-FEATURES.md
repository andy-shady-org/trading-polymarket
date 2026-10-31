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

### FEAT-101: Up/Down tick recorder and maker study
* **Class / Priority:** Income (research) · P2
* **Goal:** find out whether a maker can earn on the crypto Up/Down markets, and when. The crypto-updown study (45 minutes of ticks, 18,678 trades) found makers at about break-even before the 20% fee rebate (−0.41 c a share on 5-minute markets, −0.07 c on 15-minute ones) and, noisily, earning in the last minute (+3.7 c at 30–60 s left on 5-minute markets) and losing at 2–5 minutes left (−1.5 c). That needs 24–48 h of ticks to say with any confidence.
* **Design:**
  - `trading-polymarket ticks`: a research command, record-only, run in tmux on the Mac. Subscribes to a spot ticker (Coinbase, which matched settlement 93–99% of the time on minute data) and to Polymarket's market WebSocket (best bid and ask, book depth near the top, trades) for the open Up/Down markets of chosen assets and windows; writes daily JSONL under `data/ticks/`. The scratchpad prototypes from 2026-10-30 (`recorder.py`, `ticks_analyze.py`, `maker.py`) are the starting point, rewritten to this repository's standard with tests.
  - `trading-polymarket ticks-report`: per market and phase (time to expiry), maker P&L per share against settlement, before and after the rebate; adverse selection (the mid one, five and thirty seconds after each fill); spot moves before fills; book imbalance `(bid depth − ask depth) / (bid depth + ask depth)` at each fill.
  - **The maker study:** a simulated quote at the best bid or ask, counted as filled only when a trade prints **through** its price (never on a touch, so queue position cannot flatter it), with two pull rules taken from CloddsBot's crypto strategies and tested here: pull on a spot move above a threshold, and shorten or pull when book imbalance turns against the quote. Phases kept only where the simulated maker earns in both halves of the recording.
* **Then:** if a phase earns after adverse selection on two separate recordings, a maker lane needs live order placement (`LiveExecutor`, `LIVE-TRADING.md`), which paper cannot judge honestly (the sports study's note); it would start at Stage 2 with a tiny size, not as a paper pilot.
* **Dependencies:** none for the recorder; live execution for a lane. **Impact:** the only seat in these markets the studies so far leave open.

### FEAT-102: Full-set scanner: both sides, depth, duration, loop
* **Class / Priority:** Income (research) · P2
* **Goal:** measure, over a week, whether buying a complete set of outcomes for less than it pays is a real opportunity. Saguillo et al., "Unravelling the probabilistic forest: arbitrage in prediction markets" (arXiv 2508.03474), found such gaps were taken on Polymarket at scale; CloddsBot's version checks mid prices and binary Yes + No pairs, which on Polymarket are one mirrored book. `trading-polymarket arb` (`research/arb.py`) already checks binary pairs and neg-risk Yes sets at the best asks, but it has never been run (no `data/arb.jsonl` in `runtime-trading`).
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
