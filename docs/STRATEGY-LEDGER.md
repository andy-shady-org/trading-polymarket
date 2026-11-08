# Strategy ledger

Every strategy the project has tried or seriously considered, on every
venue, with its evidence, its verdict and why it failed or what it is
waiting for. It also says what the markets taught us, how to test a
strategy on a new chain or venue, and what makes no sense to test again.
Its companion, [`LESSONS.md`](LESSONS.md), lists the rules learned along the
way.

> [!NOTE]
> **This page is shared.** The master copy is trading-core's
> `docs/STRATEGY-LEDGER.md`. Every repository built on trading-core carries
> an identical copy at `docs/STRATEGY-LEDGER.md` (trading-core's
> `docs/dev/DOCUMENTATION.md` §2.4). Change it in trading-core, then copy it
> unchanged to every repository; never edit a copy.

**Sources.** Every number here comes from a results log or a run record,
named in words as "repository RESULTS §n" (each repository's
`docs/dev/RESULTS.md`) or "repository run `name`" (its `docs/dev/runs/`).
Results before 2026-10-28 come from pumpfun-trading, the bot trading-pump
replaced; its records are in trading-pump (`RESULTS.md` §6.1–§6.13 and
`docs/archive/pumpfun-trading/`). When this page and a results log
disagree, the results log wins and this page is corrected with a dated
line. **Status** (what is running now) lives in each repository's
`docs/dev/RELEASE-GATE.md` §1, not here.

Contents: [1. The short version](#1-the-short-version) ·
[2. How a lane is judged](#2-how-a-lane-is-judged) ·
[3. The ledger](#3-the-ledger) ·
[4. What the markets taught us](#4-what-the-markets-taught-us) ·
[5. Testing a strategy on a new chain or venue](#5-testing-a-strategy-on-a-new-chain-or-venue) ·
[6. Do not test again without new evidence](#6-do-not-test-again-without-new-evidence) ·
[7. Leads not yet judged](#7-leads-not-yet-judged) ·
[8. The strategy library](#8-the-strategy-library) ·
[9. History of this page](#9-history-of-this-page)

## 1. The short version

From pumpfun-trading's first commit (2026-10-09) and first paper pilot
(v0.2.0, 2026-10-16) to 2026-11-03: **no lane has passed a pre-registered verdict, and no money has
been traded live.** Every result below was measured in paper, replay or
offline on recorded data, with every fee priced in.

1. **Buying Pump.fun launches loses, whatever the exit.** About 25,000 paper
   trades in rc.5 to rc.8, every setting negative: rc.6 to rc.8 lost 3.9–5.5%
   a trade (rc.5's numbers are void, BUG-145); the first 24 h capture lost
   −0.579 SOL over 1,675 buys (10.3% won). Most launches never get a second
   buyer.
2. **Waiting for demand on the bonding curve does not pay either.** Confirmed
   momentum, pre-graduation and screen-rejected movers all lost 6–14% a
   trade at our 1.5 s latency (trading-pump RESULTS §6.11).
3. **PumpSwap graduates are a race against the operator's dump.** 64–77% of
   graduates crash below half their 60 s price within 30 minutes, mostly
   in a single reading; instant-band coins are dumped at their running
   peak. The momentum lane sits about break-even
   after a 2.4% round trip; the instant lane's edge was one regime's pump
   height and vanished a day later. Both lanes closed 2026-11-03 after 61
   exit rules, 105 entry variants, an adaptive gate and 222 supply-map
   combinations all failed the design gate (§6.20, §6.21).
4. **No filter, copy list or book made a lane pay.** Wash-trade and
   buy-timing inputs, creator books and copied wallets did not beat a random
   cut on unseen data; wallet diversity, a 6-buyer count and the bundle proxy
   did beat one, and the lane still lost; time-of-day effects changed sign
   between captures.
5. **A slow trend rule on liquid Solana tokens is cheap to trade and has no
   edge:** −37.8% compounded over four unseen half-years (§6.15).
6. **Other chains look good on price lists and are not trusted until a sale
   is simulated.** four.meme is NO-GO (too few graduates). Meteora DAMM v2
   on Solana, PancakeSwap v2 on BSC and Uniswap v2 on Base were positive in
   an exploratory re-reading of scout-1 and are being measured properly
   (§7).
7. **Polymarket:** day-ahead weather and the favourite–longshot bias are
   NO-GO; the market forecasts better than our models. Intraday weather and
   the Fed lane (Polymarket against Kalshi) are in paper on limited
   evidence. Sports across venues has no edge. On crypto Up/Down, taking
   at market prices loses to the fee (FEAT-146); cheap asks left stale by a
   spot move are lifted within a second, but on three days of recording we
   were fast enough for 90% of them, so the pre-registered rule is tested
   on a fresh window from 18 Nov (FEAT-147, §7). Making the market there
   earns only for a maker who reprices within milliseconds: at our speed
   every phase loses (FEAT-101).

What carries forward is not a strategy but a **method** (§2), a set of
**facts about these markets** (§4), a **playbook for the next venue** (§5)
and a **list of ideas not to repeat** (§6).

## 2. How a lane is judged

Every module uses the same method. A lane that skips a step is not judged.

**The capital stages** (trading-core's `docs/dev/DOCUMENTATION.md` §6):
Stage 0 evidence on recorded data, Stage 1 paper, Stage 2 live canary at
the smallest size, Stage 3 scale-up. A lane climbs one stage at a time on
its own pre-registered verdict; a changed rule starts again at Stage 0.

**The pre-registered verdict** (`trading-core-audit verdict --rules F`),
fixed and hashed before a counted run starts and never changed after. The
values used for every PumpSwap run (rc.9 to rc.11):

| Check | Value |
|---|---|
| Positions | at least 100 (Polymarket: 60–200 by lane) |
| Adjusted net | above 0 after a 50 bps exit haircut and a 25,000-lamport tip floor a leg (resolution lanes: no haircut) |
| Halves | both halves of the run positive |
| Days | at least half the UTC days positive (Polymarket 55%) |
| Without the best | positive without the 3 best positions (Polymarket 3–5) |
| Interval | 90% bootstrap interval of the mean per position above 0 (10,000 samples, seed 7) |

**Before a counted run, the design gate.** A candidate must be positive on
every design capture on its own at the base cost (PumpSwap: 125 bps a
side), and not negative at a stress cost (200 bps); among those that pass,
the best **worst** capture wins (trading-pump `PUMP-12-PLAN.md` §2). If
nothing passes, there is no run (LESSONS §1.6).

**The other checks, every time:**

- **Beat a random cut** of the same size, per half, on two captures, for
  any filter (`trading-core-audit cuts`).
- **Judge on what was known at entry:** the first check only; later
  failures are traps, a rug while held a total loss (trading-scout
  `readout/entry.py`).
- **Several groups judged at once:** correct the interval for the number of
  groups (scout-2 uses a Bonferroni 1.25% lower bound for four groups).
- **Replay parity:** a replay of the run's own capture matches the run's
  positions and net before any sweep on it is trusted.
- **Costs from real swaps,** checked against the module's maths
  (trading-pump §6.16).
- **Model probabilities, not just PnL,** where a lane prices an outcome: a
  model whose Brier score is not below the market's is not an edge
  (trading-polymarket).
- **Run length** from the expected count: `--run-for`, and a paper run that
  must reach a count uses the `"baseline"` breaker reference.
- **A learner** (adaptive target, rule selector, model) is judged
  walk-forward against the best fixed rule chosen in advance, with the
  learning rule frozen (trading-pump ADR-010).

## 3. The ledger

Per trade means net per position as a share of its stake, after every
cost. "Reopen if" names the new evidence that would justify a new,
pre-registered test; without it the idea stays closed.

### 3.1 Pump.fun bonding curve (pumpfun-trading, 2026-10-16 to 10-28)

| Strategy | What it did | Evidence | Result | Verdict | Why | Reopen if |
|---|---|---|---|---|---|---|
| Launch sniping, first pilot (v0.2.0) | Buy at the create event, 0.01 SOL, 300,000-lamport tips | 13.9 h paper, 1,159 buys | Reported **+63.53 SOL** (97% of sells "won"); corrected **about −0.75 SOL over 1,024 positions, −7.3% a trade, 19% won** | Invalid result (BUG-104, BUG-105) | Non-standard curves priced 25–3,500× off; a per-sell win rate; replay "agreed" because it read the same wrong prices | — |
| Launch sniping (`entry_mode: launch`) | Buy at the create event after a screen | v0.2.1 pilot (34 positions, 2 won); v0.2.3 24 h capture; rc.5–rc.8, about 25,000 paper trades | v0.2.3 −0.579 SOL over 1,675 (10.3% won); rc.8 −4.69% and −4.71% a trade over ~9,850 each; rc.7 −3.9%; rc.6 −5.5%; zero-cost rc.6 still −0.7% | NO-GO | Most launches get no follow-on buyer; exits cannot save a position with no demand; costs ≈ 4.4–4.6% a round trip | Never on this venue at seconds latency |
| Launch A/B, rc.4 and rc.5 | Sell all at 1.10× with a 0.80 stop, or hold 90 s with a 0.40 floor | 13.9 h paper (24 h planned), 1,402 + 1,369 buys | Reported +3.165 SOL; the 995 real fills lost −1.350 SOL | Void (BUG-145, BUG-146) | 29% of buys were fallback fills; coins already complete were bought | — |
| Fill-drift guard on launches | Refuse a fill more than 15% above the create market cap | rc.6, rc.7, rc.8 | −4.69% → −3.27% a trade (rc.8, both halves); with the tiny-creator-buy skip −2.87% | The one entry rule that held on every dataset; still a loss | Cuts the worst fills, cannot create demand | Use as a guard on any lane that fills after a signal |
| Exit grids on launches | Stops, take-profits, trailing, half-and-trail | rc.6–rc.8 recorded paths | Best about −3.5% a trade (rc.7); higher TPs and trailing worse | NO-GO | The entry is the problem | — |
| Confirmed momentum (FEAT-51/52) | Watch, promote on +3 SOL curve growth, buy on ≥ 3 buyers and ≥ 0.5 SOL inflow in 30 s | v0.2.3 (in-sample grid of 162), rc.1, rc.2, rc.3 paper | v0.2.3 replay +0.062 SOL / 132 after the latency fix (was +0.139); rc.1 paper −0.099 / 118; rc.2 +0.014 / 105 (about −0.007 with honest exits); rc.3 **−0.179 / 127, 14% won, 90% interval [−0.0021, −0.0010] SOL** | NO-GO (§6.11) | Selection, not costs: without fees the average position still fell 2.6%; stops filled at 87% of a 92% stop | — |
| Stricter buyer counts (6, 8, 10 buyers) | Wait for more distinct buyers | v0.2.3, rc.1, rc.2 | 8 buyers positive in-sample, −0.024 on rc.1's unseen half | NO-GO | Waiting enters later and higher | — |
| Stop-loss redesign | Arm late, hold while buys come in, hard floors, tighter stops | v0.2.3, rc.1, rc.2, rc.3 sweeps | Late arming and holding lost in every half; stop 0.92 beat 0.85 in 6 of 6 halves by noise-sized amounts (adopted for rc.3); rc.3 0.80 / 0.85 / 0.92 all ≈ −0.20 SOL | Stop 0.92 adopted; lane NO-GO | The stop is not the problem; stop positions are coins that keep falling | — |
| Early take-profit (tier 1 at 1.2–1.3×) | Take +20–30% early | v0.2.3, rc.1, rc.2 | Worse in at least one half on every capture | NO-GO | The lane's profit was a few positions running past +50% | — |
| Pre-graduation lane (FEAT-53) | Buy curves at 75–88% progress, sell tranches before completion | rc.2 and rc.3 pilots; what-if on 562 discovered curves | rc.2 2 positions −0.008; rc.3 0 trades; what-if about −14% a trade (−1.62 SOL at 0.02 SOL), both halves; −13% with other bands | NO-GO | Loses with or without the stop and in other bands; the lane saw 4 of ~2,100 watched curves pass 75% | — |
| Screen-rejected movers | Momentum on coins the screen rejected | rc.3 20% reject sample | About −10% a trade (watched coins −6%) | NO-GO | The movers the screen rejects are insider pumps | — |
| Pullback entry (FEAT-59) | Buy the first base after a 30–70% dump | rc.1, rc.2, rc.3 shadow | Trade kind 10–11 signals a day, worse than random in 3 of 4 halves; curve kinds all lost (pilot −0.080, 11% won); best shadow −0.010 / 18 on rc.3 | NO-GO | Few signals; dumps rarely base | — |
| Wallet diversity and sniper volume (FEAT-56) | Skip top buyer ≥ 50%, diversity < 0.3, early inflow ≥ 5 SOL | v0.2.3, rc.1, rc.2, rc.3 | Each rule beat a random cut on v0.2.3 and rc.1, and diversity alone again on rc.2 and rc.3; the FEAT-56/57 combination fell below a random cut in rc.3 half B | NO-GO as a lane rule | Beating a random cut on a losing lane still lost (rc.1 only to break-even, rc.3 negative) | — |
| Wash-trade inputs (FEAT-57) | Skip round-trip share > 0.1–0.4, quick flips | v0.2.3, rc.1, rc.2 | Helped on v0.2.3 only; no better than chance on rc.1 and rc.2 | NO-GO | — | — |
| Buy-timing filters (FEAT-60) | Gap regularity, bursts, size regularity | v0.2.3, rc.1, rc.2 | None beat a random cut in both halves on either capture | NO-GO | — | — |
| Bundle proxy (FEAT-61) | Early non-creator holders ≥ 1% at screening | rc.3 shadow | Beat a random cut in both halves, still lost | Recorded only | See the supply map (§3.2), which measured this properly | A lane where it changes the result per trade |
| Creator reputation book (FEAT-55) | Block a creator after one losing coin | v0.2.3, rc.1 | Blocked 203 positions worth −0.044 SOL vs −0.070 for a random 203 | NO-GO | The blocked positions were better than a random set; the serial-launcher screen already rejects repeat creators (only 2 bought twice in rc.1) | — |
| Copy trading (FEAT-54) | Copy the best wallets at our 1.5 s delay | v0.2.3 → rc.1 and back | Copying every wallet −4.67 SOL / 4,003 copies and −2.01 / 1,286; best v0.2.3 wallets lost on rc.1, worse than 97% of random wallet sets | NO-GO | The copier buys later and pays more; top "trader" was a serial creator | A capture of wallets' own trades shows our copy net positive on a second capture |
| Holder count screen | `min_holder_count: 6` | v0.2.3 replay | The only filter positive in both halves (+0.026 SOL / ~229) | Never confirmed on a second capture | The launch lane closed first | — |
| Buy after the post-graduation crash | The operator's idea from charts: buy coins that crash after graduating, for the recovery | 92-coin candle sample; rc.6 data | 0 of 39 fast graduates that fell below half within 15 minutes came back | Dropped | Charts show the survivors; it led to graduation tracking (FEAT-73) and FEAT-76 | — |
| Built, never judged | Raydium migration sniping (FEAT-05), capital rotation (FEAT-24), urgency tiers (FEAT-23), the genetic optimizer (FEAT-27), back-running and cross-venue arbitrage (FEAT-28), the sybil detector (FEAT-26) | pumpbot code | Raydium sniping never fired: Pump.fun migrates to PumpSwap (BUG-123); arbitrage only ever saw hard-coded sample reserves (BUG-90); the sybil detector needs `funding_links` the API never sends; the rest produced no result | Not ported | Wrong venue, fake inputs, or never evaluated | A new pre-registered test, from scratch |

### 3.2 PumpSwap graduates (trading-pump, 2026-10-27 to 11-03)

| Strategy | What it did | Evidence | Result | Verdict | Why | Reopen if |
|---|---|---|---|---|---|---|
| Buy at the migration | Enter at the first pool reading | rc.8 run A, 236 standard graduates | Best exit −0.02% a trade at 1% a side, −2.0% at 2%; random entry in the first 10 min −7.3% | NO-GO | Of all 569 migrations with pool rows (178 already empty), the median pool was at 0.72× its first price after 5 min and 0.09× after 15; 75–77% of standard graduates fall below half their 60 s price within 30 min | — |
| `pumpswap_momentum` (FEAT-76) | Standard graduates (first market cap 205–822 SOL) still ≥ 1.2× at 60 s; TP +20% or +50%, SL −15%, 30 min | rc.8 offline (n 42–72), rc.9 paper (55), rc.10 (8), rc.11 paper (52), rc.11-tp20 (71); engine replays | rc.9 +0.034 SOL / 55 (NO-GO on count, interval); rc.11 TP +50% **−0.018 / 52, adjusted −0.026**; rc.11-tp20 +0.009 / 71 (adjusted −0.002) | NO-GO, closed (§6.20, §6.21) | About break-even after a 2.4% round trip on every capture; 75% of standard graduates crash within 30 min | A venue whose round trip sits well under the lane's +1–4% gross edge, with the same survivor pattern |
| `pumpswap_instant` (FEAT-78) | Instant graduates (1,000–2,000 SOL, 130–200 SOL pool) at 1.00–1.10× at 60 s; TP +50%, SL −15%, 30 min | rc.9 replay; rc.11 paper; rc.11-tp20 | rc.9 replay **+17.7% a trade / 80**; rc.11 **−0.477 SOL / 245, every day negative, stops filled at −44% median**; rc.11-tp20 (TP +20%) −0.335 / 405 | NO-GO, closed | Every instant coin is a bundle dumped at its peak in one step; the edge was rc.9's pump height (median peak 2.3× vs 1.3× a day later) | — |
| Wider and lower take-profits | TP +15% to +50%, holds 4–30 min, the adaptive target, tiers, break-even stops (61 rules per lane; §6.21 added TP +10% and 2–3 min holds on the supply-map groups) | rc.8, rc.9, rc.11, rc.11-tp20 | Every instant rule −2.7% to −4.5% a trade on rc.11; best momentum rule −0.6% on rc.11 | NO-GO by the design gate | A lower target raises the win rate and the break-even together | — |
| Entry variants | Momentum ratio 1.1–1.5 at 60–180 s; instant band 0.9–1.3 at 30–120 s | 105 variants, same captures | Best momentum +1.1 / +2.8 / −0.4 / +3.3% on the four captures | NO-GO | — | — |
| Short holds | TP +6–20%, SL −10 to −30%, 60–180 s | 75 rules | One momentum rule passed (TP +20% / SL −30% / 3 min) but every neighbour failed | NO-GO | A lone peak is overfit | — |
| Adaptive take-profit | Lower quartile of the last 6 h of peaks × 0.9 | rc.9 vs rc.11's first night; design gate | +12.0% and +8.8% on two periods, sign flips with memory length; design gate −3.0% on rc.11 | NO-GO | Noise on 22 trades | — |
| Adaptive gate and rule selector | Trade only when the best of 6 shadow exit rules is positive over the last 10 closes | Walk-forward rc.9 → rc.11-tp20 | Instant −0.275 → −0.019 SOL; momentum −0.004 → +0.075 SOL, but both lose in rc.11's second half; rc.8 −3.6% | NO-GO by the design gate | Stands aside in bad hours; does not make a bad period pay | A lane whose fixed rules pass in most regimes |
| Per-lane pause (trading-core FEAT-81) | Stop a lane after a losing streak | rc.11's first night only (22 entries); rc.9 replay | Trimmed the loss at TP +50% (−0.091 → −0.078 SOL); at TP +30% turned −0.029 into +0.016 SOL on 18 trades (noise-sized); the adaptive gate, which does the same, failed the design gate | Kept as risk control | — | — |
| Supply-map filter | Holders at the migration from the curve's transactions (identical balances, holder count, top-5 share) | 902 instant graduates | Predicts crashes (81% vs 42% on rc.9, p < 0.001; same direction on all three); the lane still loses without the bundled coins | NO-GO as a filter (§6.21) | Bundled coins also pump highest first | Record it on any reopened lane; judge per trade |
| Operator tags, creator funders, mayhem flag | Name seen before, shared funders, fresh or busy creators | 2,086 graduates (A5) | No tag separates crashes on all three captures with a matching lane result | NO-GO | — | — |
| Stall exit, rug alarm (FEAT-93, FEAT-100) | Exit when activity stops before a dump | 18 crashed coins' transactions (A6) | Nothing a 1–2 s reader can act on; dumps are ~20 identical sells in one slot | NO-GO | — | Slot-level reads of the mapped holders |
| Time of day and weekend | Trade only in good hours or days | rc.8 to rc.11 | Sign changes between captures | NO-GO | — | — |
| New non-graduate PumpSwap pools (FEAT-80, pools-1) | Buy new SOL pools at the first reading or at 60–90 s | 3,122 pools in 71.7 h | −12.5% a trade at the first reading; −2.3% at 60–90 s (−10.9% and −0.4% at a 30 bps fee); 92% lose four fifths of their SOL within an hour | NO-GO | Liquidity withdrawn; no rule positive at either fee | — |

*Momentum re-read 2026-11-04 under ADR-012.* rc.9's "NO-GO on count" would
be **EXTEND** today, but the captures after it decide it: on rc.8, rc.9 and
rc.11 the best rule (adaptive target, 30 min) makes −0.1%, −0.4% and −0.5% a
trade at 0.02 SOL (2.5% fee, 0.5% haircut, 0.35% fixed). Size does not
rescue it on PumpSwap: at 0.05–0.1 SOL the worst capture improves by 0.15
points to −0.34%, and from 0.3 SOL the pools' depth (median 101 SOL at entry)
costs more than the fixed part saved (worst −0.70% at 0.3 SOL, −2.0% at
1 SOL). The mechanism's gross edge (about +3% a trade before costs) stands;
scout-2 and evm-1 test it where the round trip is a quarter as large.

### 3.3 Liquid Solana tokens (FEAT-65 slow lane, 2026-10-23 to 10-29)

| Strategy | What it did | Evidence | Result | Verdict | Why | Reopen if |
|---|---|---|---|---|---|---|
| Daily trend rule in SOL terms | Hold a token above its N-day mean (N 10 / 20 / 50), else SOL | 132 days of GeckoTerminal bars; then Binance daily bars 2021-08 → 2026-10, walk-forward, pre-registered | Costs pass (median round trip 0–37 bps); walk-forward −0.6 / −17.3 / −17.1 / −8.6% in four unseen half-years, **−37.8% compounded**, below the random-entry p90 in all four | NO-GO (§6.15) | Holding SOL beat both; every training window had all three rules negative | A new pre-registered rule, not a variation of this one |
| Hourly trend rule | Same on hourly bars | 188 days, 5 tokens | −20.2 / −13.0 / +7.4% vs buy and hold +46.3% | NO-GO | Whipsaw: 555–1,243 switches | — |

### 3.4 Other chains and launchpads (trading-scout, trading-evm)

| Strategy | What it did | Evidence | Result | Verdict | Why | Reopen if |
|---|---|---|---|---|---|---|
| Trending and volume lists | Buy coins on 5 m / 1 h trending or 24 h volume lists | rc.8 market recorder, 38.2 h | Base −3% to −4% a trade at 2% a side; noise elsewhere | NO-GO | Lists show what already moved | — |
| Best-looking new-pool groups by price list | Base Uniswap v2, BSC PancakeSwap v2, Base v4 after +50% | rc.8 recorder | 90–96% "wins" at 1.2× with no stop | Not evidence | The signature of honeypots and sale taxes; no sale simulated | A sale check on every exit (scout-2, evm-1) |
| four.meme graduates (BSC) | The FEAT-76 pattern on four.meme's PancakeSwap pairs | scout run `scout-1`, 72 h | 34 graduates (100 needed), 2 checkable | NO-GO (rules 1 and 2) | Its coins rarely graduate (one every ~2 h) | Volume grows ~3× |
| FEAT-76 rule on many groups, first check only | Signal 60–120 s after the first snapshot, $5,000 liquidity at entry, pool drained = total loss | scout-1 exploratory re-reading | DAMM v2 156 trades +16.3%; BSC PancakeSwap v2 1,231 +7.8%; Base Uniswap v2 107 +16.9%; Pump.fun graduates 98 −6.0% | Exploratory (8 groups, 2 rule versions) | 30 s list snapshots; EVM sales not simulated at exit | Being measured: §7 |
| Moonshot, Virtuals, SunPump | Other launchpads | rc.8 counts | Moonshot 18 pools in 38 h; no Virtuals id; Tron not recorded | Not tested | Too small to judge (Clanker is not: it deploys Base's Uniswap v4 pools, judged in scout-2) | Volume to judge a rule on |
| Meteora DBC graduates | The FEAT-76 rule on `meteora-dbc graduate` pools | scout-1 exploratory re-reading | 59 trades, +7.4% a trade (halves +11.1% / +3.4%), not positive every day | Exploratory | Their pools can lock the creator's liquidity: a test of whether that dumps less (trading-scout FEAT-104) | A design gate pass on an on-chain capture |
| Locked-liquidity launchpads (by launcher in scout-2) | The FEAT-76 first-check rule split by launchpad | scout run `scout-2`, 72 h (trading-scout RESULTS §4; project note `claude/rug-backtests-2026-11-07.md`) | No traps on Base `bankr` (120 entered), `o1-launchpad` (71) or Robinhood `clanker` (7), against 82% on Base v2 pairs and 93% on BSC v2; but only 0–1.7% of their pools reached 1.2× in 15 minutes (47–77% for v2 pairs), and the rule made no trade on them | NO-GO as a venue for this rule | No rug and no move: what makes them safe also keeps the price still | A launchpad with locked liquidity whose pools move |
| Liquidity custody at entry (FEAT-170) | Enter only pairs whose LP is 90%+ burned or held by a contract | scout-2's 366 v2 trades re-read with `trading-evm custody` (exploratory) | 89–100% of trades had 90% or more of their LP in wallets; the 35 with secured LP were never pulled (the rest 99% on BSC), but 79% of BSC's were trapped through the token instead; BSC mean +9.8% (34) against +4.5% (285) | Exploratory; too few to judge | A pull needs the LP in a wallet; a honeypot does not | A capture where secured pairs are common, judged per trade with its sale checks |
| Precursor tripwire on EVM v2 pulls (FEAT-170) | Sell on the token's own events or LP-token moves before a pull | The same 366 trades: 323 pulls | **0 of 323** pulls had any token event or LP move before them; the LP never moved before it was removed, a median 6–7 minutes after entry (BSC: 5% within 3 minutes, 78% within 10) | NO-GO | The first thing on chain is the pull itself, as on pump.fun (§3.2) | — |
| DAMM v2 pools by creator (damm-1) | Drained and crashed shares by how many pools the creator made | damm-1's capture (exploratory) | Creators of 100+ pools (5,876 of 6,518 pools read): 57% drained, 49% below half within 30 minutes; one-off creators (194): 18% and 6% | Exploratory | One wallet made 5,370 of the capture's 12,307 pools | `damm-2`'s launcher split (its run record, dated 2026-11-07) |

### 3.5 Polymarket (trading-polymarket, 2026-10-28 to 11-03)

| Strategy | What it did | Evidence | Result | Verdict | Why | Reopen if |
|---|---|---|---|---|---|---|
| Weather, day-ahead | Forecast model against temperature buckets, entry at local midnight | 3,124 events, 1 Aug–27 Oct | 2,458 trades, −$4,604; Brier model 0.067 vs market 0.057 | NO-GO | The market forecasts better | — |
| Weather, intraday (late day) | Remaining forecast plus today's error, entry 15–16 h local | 757 events 12–27 Oct (in-sample); paper `weather-0.2.0` | Replay 15 h +$1,102.70 / 306 and 16 h +$1,213.88 / 158 (weights chosen on this window); paper 0.2.0 model −$99.8 on 10 positions of one thesis | INCONCLUSIVE (data-limited); paper `weather-0.2.1` | The 0.2.0 model priced a further rise at 20–35% where ~7% happens | Its own Stage 1 GO, and Brier below the market again on the run's METAR archive |
| Favourite–longshot bias | Buy favourites 0.80–0.97 near close | 4,454 resolved markets; test 1,403 | −$22 / 5, −$33 / 95, −$147 / 746 | NO-GO | Favourites won less often than priced on this venue | Calibration by category and by event, on a new window |
| Fed: Polymarket vs Kalshi | Buy Polymarket buckets below Kalshi's price, sell on convergence | 16 meetings, 58 buckets | +$25.08 / 23 (adjusted +$23.15); held to resolution −$2.51 | INCONCLUSIVE (sample-limited); paper `fed-0.2.1` | The PnL is selling into convergence; neither venue forecasts better | Its own Stage 1 GO on 60 positions |
| Sports across venues | The Fed rule on Polymarket and Kalshi games | Study of 2026-10-30 (project notes, not in a repository): 2,063 live sides; 503 settled games | Median gap 0.5 c, p90 1.0 c; the rule triggers 0 times in major sports | NO-GO (study) | Venues are arbitraged to half a cent; the taker fee is larger | Listing-time gaps in tennis and esports, from recorded books: the recorder is built (trading-polymarket FEAT-168) and `sports-1` pre-registered, 2026-11-07 |
| Crypto Up/Down taker | Lognormal fair value from spot vs the market | Study of 2026-10-30 (project notes; maker figures in trading-polymarket FEAT-101): 2,940 markets (minute data); 45 min of ticks | +20–50% a trade on stale prices; −1% to −12% at the next print; market log-loss 0.30 vs model 0.36 | NO-GO (study) | Minute data hides the repricing; the market is more accurate | Reopened for the seconds after a spot move: FEAT-147 (2026-11-04) |
| Crypto Up/Down maker (FEAT-101) | Quote only in the phases makers earn | 18,678 trades in 45 min; then three days of `ticks` (4–7 Nov, 865 BTC 5-minute markets), a simulated quote filled only on a print through it | A maker always at the top: +1.82 c a share after the rebate, 5 of 6 phases positive in both halves; 99.8% of its fills come within 250 ms of the price reaching the top. With our quote as the top was L ms before: +1.52 c at 10 ms, but −0.92 c at 25 ms and −1.96 c at 100 ms, every phase negative from 25 ms (250 ms −2.29 c, 1 s −3.11 c) (trading-polymarket RESULTS §2, 2026-11-07) | NO-GO at our speed (study) | The fills go to makers who reprice within milliseconds; our round trip is 117 ms, and the quotes we would leave at the top are the stale quotes takers pick off | A passive quote behind the top earning, on a recording with depth at each level (the recorder keeps the top only) |
| Crossvenue (any reviewed Polymarket / Kalshi pair) | The Fed rule on pairs a human approves | First `pairs suggest`: 53 candidates, mostly long-dated, with traps a title match cannot see | — | Built; no Stage 0 (no pair approved) | Arbitrary pairs have no history | Approved pairs and a recorded dry run of two weeks or more |
| Momentum (research) | Buy markets that moved ≥ 8% in the last hour, record attention | Never run | — | Off; no stage | No edge claimed | Its own pre-registered Stage 0 |
| Full-set scanner (FEAT-102) | A neg-risk event's Yes set (pays 1) or No set (pays n − 1) bought below its payout after fees; binary Yes + No pairs dropped (the No book mirrors the Yes book, so a pair costs 1 + the spread) | Built 2026-11-07 (trading-polymarket 0.6.0): every open neg-risk event (about 7,300, 114,000 markets), every set's books every 5 minutes, open gaps every 5 s. A first live pass found 65 "open" sets, all missing an outcome (TP-13); with that fixed, 10,768 full sets and 2 open in a sweep, worth $2–3 | — | Run `arb-1` pre-registered (8 days) | Legs cannot be bought atomically; an executor needs multi-leg orders | ≥ 10 gaps a day of ≥ $5 lasting ≥ 10 s, on 5 in 7 covered days (`arb-1`) |
| Expiry fade (FEAT-103) | Buy the side 15 c or more from 0.50 with 5 to 1 minutes left and spot flat (under 6 bp in a minute); its mirror buys the favourite (CloddsBot's rule) | Every taker trade of FEAT-146's 8,615 BTC 5-minute markets and one-second spot; pre-registered 2026-11-07 | Primary: −8.0% on stake over 6,139 entries (halves −11.1% / −4.7%; −15.2% without the best 1%); won 26.5% at an average 26.8 c. Mirror −1.4% (7,335); 10 c, 25 c, no spot filter and 3 s late all lose | NO-GO | Both sides win about as often as priced; the fee, largest near 0.50, is the loss | — |
| Crypto Up/Down late longshot (FEAT-146) | Buy the side at ≤ 5 c from 240 s into a BTC 5-minute window, filled at the next real buy print, held to settlement; the pattern of the wallet `@vega7` (+$33.7K on $81.8K) | Every taker trade of 8,615 BTC 5-minute markets, 2026-10-05 to 11-03; pre-registered | Primary: −$3,802 on 4,500 entries (−16.9% on stake; halves −26.9% / −7.8%; −84.5% without the best 1%); won 2.07% at an average 2.23 c. All 9 other caps (2–10 c) and start times (from 0 to 270 s) lose 17–44% | NO-GO | Cheap sides win slightly less often than priced and the fee is ~7% of the stake; the wallet's profit is selection or luck in a few fat-tailed wins (without its 50 best markets it lost) | A pre-registered condition known at entry (spot against the start price, say) that is positive in both halves of a new window |
| Crypto Up/Down stale quotes after a spot move (FEAT-147) | Buy a side priced ≤ 5 c right after Binance moves to or past the start price in its favour, before makers reprice; what the bot `@vega7` appears to do | Study of 2026-11-04 on FEAT-146's backfill (in-sample): every cheap buy print in the last 3 minutes of 8,615 markets against one-second Binance spot; then a 6-minute live recording (`ticks`) | Read against the data API's print times: +163% on stake with spot 2 s before the print, −30% at 5 s. But those times run a median 2.2 s **after** the fill (1,302 fills matched by transaction hash): "2 s before" is about the fill's own moment. With that correction the pre-registered rule loses even in-sample (−4.3%; 1 s late −7.2%; every variant ≤ +1.7%). Part 1 on three days of `ticks` (4–7 Nov): 248 of 276 signals (89.9%) outlived our 251 ms delay; of the 148 asks that repriced before the window closed, 81% did; offset 2.20 s (trading-polymarket RESULTS §2, 2026-11-07) | Lead; part 1 takeable (2026-11-07); part 2 pre-registered on 4–17 Nov, from 18 Nov | We are usually fast enough to reach a stale ask; whether buying them earns is part 2's question | — |
| Crypto Up/Down steady winners' habits (study, 2026-11-08) | Do what wallets positive in both halves do: enter late, never sell, buy one side, buy after Binance moves toward the side | FEAT-146's 30 days fetched again (8,615 markets, 12.9M taker trades) and Binance's one-second spot, print times moved 2.20 s earlier; wallets' traits measured on one half and judged on the other; every taker buy by window time and prior spot move; a one-entry rule in 16 variants (trading-polymarket RESULTS, 2026-11-08) | 492 wallets in 100+ markets positive in both halves made +$550K on $30.8M, but −$37K without each wallet's best 1% of markets. Next half positive (26.8% of 3,177 overall): 34% of wallets that never sell against 14% of the heaviest sellers; 37% of the latest entrants against 22%; 32% of one-side wallets against 21%; 38% of those buying mostly at 95 c or more, the only group above zero (+$3.9K). Every taker buy, held to settlement, after a ≥ 2 bp 10-s move toward the side, at 180–300 s and ≤ 95 c: +0.5 to +0.8% when the move ended 1–2 s before the fill, mixed by 3 s; buys against a move −4 to −11%. As one entry a market, 15 of 16 variants fail FEAT-147's bar, and the one that passes fails its 2 s stress | NO LEAD (exploratory) | The winners' edge is thin and fat-tailed; what persists is holding to settlement on one side, and what pays market-wide is the sub-second spot lead FEAT-147 already tests | The one passing cell positive on a fresh window beside FEAT-147 part 2 (reported, not judged), then its own pre-registration |

### 3.6 Listed tokens (trading-scout, 2026-11-07)

| Strategy | What it did | Evidence | Result | Verdict | Why | Reopen if |
|---|---|---|---|---|---|---|
| Short newly listed perpetuals (FEAT-173) | Short Hyperliquid perps from day 1, 3 or 7 after listing for 30 or 90 days, squeeze stop at 2×, funding and 4.5 bps a side | Study `listings-1` (trading-scout `docs/dev/runs/listings-1.md`, pre-registered), 235 coins, daily candles | Primary cell −8.7% over 224 shorts (median +4.9%, 54% won); 22% hit the squeeze stop; the same short 180+ days after listing +5.6% | NO LEAD | Most listings fall, but the few that run wipe out the rest, and newness adds nothing over shorting older coins | A venue or data that names a coin's true first listing, with intraday prices |

## 4. What the markets taught us

Facts measured on real data that any design on these venues starts from.

**Memecoin launches (Solana, and the same shape elsewhere)**

- **Most launches never get a second buyer.** Pump.fun launches about
  24,000 coins a day; buying at the create event lost on ~25,000 paper
  trades whatever the exit.
- **Graduates are dumped.** Within 30 minutes 64–67% of instant-band and
  about 75% of standard-band PumpSwap graduates fall below half their 60 s
  price; 78–85% of instant crashes and 54–60% of standard ones happen in a
  single reading (2 s for the first 5 minutes, 10 s after). Standard-band
  coins fall from about 0.7× their peak.
- **Instant coins are dumped at their running peak** (1.00× the peak, 1.4–1.7×
  the first price), by about 20 identical sells in one slot. The whole curve
  is bought in the creation slot by 3–5 signers; about 7 holders at the
  migration; the creator keeps under 0.4%.
- **Operators use a fresh wallet per coin** (253 creators for 258 coins)
  and reuse names (79% of instant coins share a name with another).
- **The edge is the pump height, and it moves.** Median peak 2.3× one day,
  1.3× the next.
- **No sampled coin that crashed below half in its first 15 minutes came
  back** (0 of 39). Charts show the survivors.
- **The screen keeps the quiet coins.** Coins rejected for top-holder or
  creator concentration moved more and were worse to trade.
- **Non-graduate new pools are drained:** 92% lose four fifths of their
  pool within an hour.

**Costs and execution**

- **Fixed costs must be sized to the position.** At 0.01 SOL, two
  300,000-lamport tips were 6% of the position (v0.2.0); with 50,000-lamport
  tips and 300 bps paper slippage a flat exit still lost about 6.4% (v0.2.1).
- **Pump.fun curve round trip** about 4.4–4.6% in paper at 0.02 SOL (1.25% a
  side plus haircuts); **PumpSwap** 125 bps a side below 420 SOL market cap,
  120 bps from 420, 115 bps from 1,470, falling further with size (on the
  mint's real supply), about 2.4% a round trip with
  base and priority fees; **liquid Solana tokens through Jupiter** 0–37 bps.
- **Stops gap through:** −19% median fill on a −15% curve stop; on
  PumpSwap's −15% stops, momentum −17% (rc.11 paper) to −24% (rc.9 replay),
  instant −25% to −44% in paper and −57% in the rc.9 replay.
- **Jito tips** were 83% of the separately listed costs at 0.01 SOL
  (v0.2.3); on the momentum lane a 0 to 100k lamport tip moved a 24 h
  replay from +0.139 to +0.109 SOL, so the landing rate, not the tip,
  decides its level.
- **Priority fees** were 0 in about 99% of slots for liquid swaps.
- **Data costs:** PumpPortal's trade feed costs 0.01 SOL per 10,000
  messages; a pool subscription on PumpSwap carried about 3 GB a day, and
  the DAMM v2 stream about 6 GB a day.
- **EVM:** PancakeSwap v2 round trip 49.9 bps, Uniswap v2 on Base 60 bps;
  Pons V2 graduates on Robinhood Chain 199–1,900 bps; gas about 0.3% of
  0.005 BNB for two swaps on BSC at 0.05 gwei.
- **Meteora DAMM v2 launch pools** charge an anti-sniper fee that starts
  near 100% and decays; their first minutes are untradeable.
- **Polymarket taker fee** is `rate × p(1 − p)`, rate 0 (weather) to 0.07
  (crypto); redemption is free; a 7% category fee at 0.90 can be the whole
  edge.

**Data**

- **List discovery is slow:** GeckoTerminal shows a new pool about 94–120 s
  after creation on Solana and 130–240 s on BSC and Base (scout-1 medians), too late for a
  60 s signal; on-chain discovery is needed.
- **Lists are wrong about new pools:** v4 pools with no liquidity show
  reserves and trades; BSC pairs valued at $55,000 held 0.0001 BNB;
  DexScreener missed 98% of LaunchLab and a third of v4 pools.
- **On EVM chains 83–94% of pools clean at the first sale check were not
  clean at the last.**
- **Most new v2 pairs are empty in their first minutes,** and many new v4
  pools hold no liquidity in range.
- **Prediction markets are hard to beat on forecasts:** Polymarket's
  prices beat our day-ahead weather model and a spot model on crypto
  Up/Down, and matched Kalshi on Fed decisions and sports.

## 5. Testing a strategy on a new chain or venue

The playbook, in order. Each step names the lesson it comes from. Skipping
one has cost a run before.

1. **Count the population.** Sample new pools by dex and kind for at least a
   day; count how many graduate or survive, and how many your checks
   support. *(four.meme: 34 graduates in 72 h; Robinhood Chain: 83% of
   pools unsupported.)*
2. **Find the dump before the edge.** Measure, on every pool, how many crash
   below half within 30 minutes and in how many steps. A population that
   is mostly dumped in one step cannot be traded with stops. *(PumpSwap
   §6.21.)*
3. **Measure the round trip from real swaps,** at the size you would trade,
   including launch fees, taxes and gas, and check your maths reproduces
   them. The round trip must sit well under the gross edge per trade: the
   PumpSwap momentum lane's best rules made +1% to +4% a trade before a
   2.4% round trip and ended about break-even.
4. **Simulate a sale before trusting a price,** at entry and before every
   exit on chains where an owner can change the token (EVM). *(scout-1.)*
5. **Record the population on chain, record-only,** at the speed the lane
   would trade (1–2 s), from its first event, following every exit for a
   while, with the fill's own read recorded. Use on-chain discovery, not
   lists. *(FEAT-72, BUG-164.)*
6. **Record what the PumpSwap lessons say matters,** even before a lane
   uses it: the deployer and its funder, the holders at the signal (top
   share, identical balances, holder count), the pool's liquidity owner and
   whether it can be withdrawn, the fee at each moment. *(§6.21 supply map;
   pools-1.)*
7. **Count the funnel and replay each excluded group as a lane.** *(§6.18.)*
8. **Design on at least three captures, choose for the worst case,** with a
   cost stress, and beat a random cut with every filter. *(PUMP-12-PLAN
   §2.)*
9. **Check replay parity** on the record-only run's capture before any
   sweep. *(§6.20 A2.)*
10. **Pre-register the counted run** with its length from the expected
    count, the `"baseline"` breaker reference, per-lane limits, and engine
    exits empty when the lane has its own. Smoke-test the runtime on live
    data first. *(rc.9, rc.11, TC-11.)*
    **Verdicts scale with the evidence** (ADR-012, 2026-11-04): GO when the
    lower bound of the mean net is above zero and the bound on total losses
    (about 3/*n* with none seen) is below the lane's break-even rate;
    **EXTEND**, not NO-GO, when the mean is positive but the bounds are not
    there yet; NO-GO only when the lane is confidently below its costs.
    State costs split into fixed, proportional and price impact, and the
    sizes at which the lane is positive. A lane need not pay for a module
    on its own: the platform adds its GO lanes up.
11. **Live at the smallest size only after a Stage 1 GO,** and compare live
    fills with paper fills before scaling.

**What carries over from Pump.fun to other chains** (what to measure there,
not a result):

| Pump.fun / PumpSwap finding | On EVM chains (trading-evm, trading-scout) | On Meteora DAMM v2 (trading-meteora) |
|---|---|---|
| Graduates dumped by bundled supply at the peak | Measure the crash rate and steps per pool kind; record deployer, funder and early holders | Measure the same per pool; record the creator, the fee scheduler and early holders |
| Fees decide the momentum lane (2.4% round trip) | v2 round trips 50–60 bps plus gas: room the PumpSwap lane never had | Read the dynamic fee at each moment; the launch fee makes the first minutes untradeable |
| Stops gap through on 2 s reads | Blocks come every 0.1–2 s (Robinhood Chain 0.1, BSC 0.45, Base 2); measure stop fills against the stop | Slots of about 0.4 s (general Solana figure); same |
| Tokens cannot block a sale (no freeze authority) | They can: taxes, blacklists, owner switches; simulate a sale before every exit | Exclude tokens with a freeze authority |
| Lists lag and lie | Discover from factory and PoolManager events | Discover from program events |

## 6. Do not test again without new evidence

Each of these has been tested or reasoned out, and a new test **on the same
venue** would only repeat it. **Scope** says where it failed: **Everywhere**
means the reason holds on any venue (do not test it anywhere); a venue
name means it failed there and may be tested on another venue through the
strategy library (§8), with the playbook (§5) and the design gate (§2).
**Library** names the trading-core feature that makes it testable on any
venue, or says why it is not brought back.

| Idea | Scope | Why not | New evidence that would reopen it | Library |
|---|---|---|---|---|
| Buying launches at the create event | Pump.fun / PumpSwap | ~25,000 paper trades lost at every exit | A venue where most launches get follow-on demand | FEAT-121 |
| Tuning exits on a losing entry | **Everywhere** | 61 exit rules per lane, every launch exit grid, all lost | A passing entry first | — |
| Faster reads or better stops against one-slot dumps | Pump.fun / PumpSwap | 160 of 171 instant stops on 2 s reads filled at −33% | A tripwire (slot-level reads of mapped holders) that fills stops no worse than −20%: at that bound the instant rules were positive on rc.9, rc.11 and rc.11-tp20 (TP +50%: +27.1%, +4.9%, +12.8%) and momentum TP +20% passed narrowly | — |
| Copying wallets | Pump.fun / PumpSwap (1.5 s delay) | Copies lose at our delay; the copier is exit liquidity | Our own copy net positive on a second capture of wallets' own trades, on a slower venue | FEAT-136 |
| Coordinated buying ("swarm") | **Everywhere** | It manufactures demand to sell into: market manipulation | Never | Not brought back |
| Cross-DEX arbitrage | **Everywhere** | Taken by co-located searchers; the legs cannot be bought atomically through one engine | Never at this infrastructure | Not brought back |
| Creator reputation tracking | Pump.fun / PumpSwap | A fresh wallet per coin | Creators that repeat (EVM deployers may) | FEAT-127 |
| Exit times per coin name | Pump.fun / PumpSwap | No better than one global time out of sample | — | — |
| Price-path filters on instant entries | Pump.fun / PumpSwap | Crashes look like the rest in the first minute | A new pre-entry feature that separates crashes on every capture and changes the result per trade | FEAT-120 (bands), FEAT-134 |
| A larger order size | **Everywhere** | The fee is a share of the order | Measured price impact in live fills | — |
| Time-of-day or weekday filters | Pump.fun / PumpSwap | Sign changes between captures | The same sign on three captures | FEAT-94 (built) |
| Buyer-count, wash-trade, buy-timing filters on a losing entry | Pump.fun / PumpSwap | Wash and timing inputs did not beat a random cut; buyer counts and diversity did, and the lane still lost | A passing entry to filter | FEAT-124, FEAT-125 |
| Trend rules on liquid tokens | Liquid Solana tokens | Walk-forward −37.8%, below random | A different, pre-registered rule or another market | FEAT-131 |
| Trending and volume lists as an entry | **Everywhere** | Show what already moved | — | Not brought back |
| Returns from price lists without a sale check | **Everywhere** | Honeypots and taxes look like wins | — | Not brought back |
| Day-ahead weather, favourite–longshot on Polymarket | Polymarket | The market is better calibrated | Category or event-level calibration on a new window | — (Polymarket lanes) |
| Major-sports cross-venue gaps | Polymarket / Kalshi | Half a cent; fee is larger | — | — |
| Buying the cheap side late in crypto Up/Down windows, unconditionally | Polymarket | 4,500 entries at ≤ 5 c lost 16.9%; every cap and start time lost (FEAT-146); up to 35 c with spot flat lost 8.0%, and the favourite 1.4% (FEAT-103) | A condition known at entry, pre-registered and positive on a new window | — |
| Quoting at the top of crypto Up/Down books from a home connection | Polymarket | Three days of ticks: the top earns +1.82 c a share only for a maker repricing within milliseconds (+1.52 c at 10 ms); at 25 ms and slower every phase loses (−0.92 c at 25 ms, −1.96 c at 100 ms, −3.11 c at 1 s) (FEAT-101) | A quote behind the top earning on a recording with depth at each level, or placement within about 10–20 ms (co-location, not a home connection) | FEAT-148 |
| Raydium migration sniping | Pump.fun / PumpSwap | Pump.fun graduates migrate to PumpSwap | — | Not brought back (the venue is gone) |
| Relaxing a holder or creator screen to get more trades | **Everywhere** | Rejected movers lost ~10% a trade against 6% for watched coins: insider pumps | — | — |
| A trade-feed stop trigger, or Yellowstone gRPC for a 60 s signal | Pump.fun / PumpSwap | The feed crossed the stop 0.07 s before the curve read, at the same price; migration events already arrive within ~1 s | A lane whose edge is lost to latency, shown in live fills | — |
| Order splitting at our size | Solana, 0.02 SOL | Each split pays the network fee again | — | — |
| "Smart money" lists (Axiom, Fomo) | Pump.fun / PumpSwap | They rank wallets the way the copy study did, and copying lost | — | FEAT-136 covers it |
| Exchange IDOs | **Everywhere** | Manual KYC, allocations, days-long holds, no bot API | — | Not brought back |
| Long-tail PumpSwap pools (graduated over 24 h ago) | Pump.fun / PumpSwap | Thin and bleeding; fixed costs a large share at 0.02 SOL | — | — |
| Moonshot | Moonshot | 18 pools in 38 h: no verdict is reachable | Its share of launches grows | — |
| Another record-only week of PumpSwap graduates | Pump.fun / PumpSwap | rc.11, rc.11-tp20, pools-1 and the supply map already hold it | A new lane design that passes the design gate on that data | — |
| Tripwires on events before a pull (token events, LP moves) | **Everywhere** (new pools) | pump.fun dumps (§3.2 A6) and 323 EVM v2 pulls (§3.4): nothing on chain comes first | A chain where a pull is seen pending (FEAT-172's mempool watch) | — |
| Shorting new listings on daily candles | Hyperliquid perpetuals | `listings-1`: the squeeze tail beats the median fall | Intraday data and a true first-listing date | — |

## 7. Leads not yet judged

As of 2026-11-03; each repository's `RELEASE-GATE.md` §1 says where each
stands now.

| Lead | Where | Why it is a lead | What decides it |
|---|---|---|---|
| Meteora DAMM v2 new pools | trading-pump `damm-1` (FEAT-107, record-only), then trading-meteora (FEAT-113) | scout-1 re-reading +16.3% a trade on 156 trades, both halves and every day positive (the pre-registered rule with only the first check: 29 trades, +21.3%, interval +13.0% to +29.6%); no freeze authority; liquidity ~$21,000 at entry. **Warning:** exits came ~1.6 min after entry, the same fast pump-and-dump shape as PumpSwap's instant graduates, whose +17.7% in-sample became −20.7% a day later; prices were 30 s list snapshots and Jupiter's best route, not the pool | A design that passes the design gate on several on-chain captures from different days, with the launch fee read from the pool |
| BSC PancakeSwap v2, Base Uniswap v2 and v4, Robinhood Chain v4 | trading-scout `scout-2` (four groups, pre-registered) | scout-1 re-reading +7.8% and +16.9% a trade | scout-2's verdict per group; sale simulated before every exit |
| EVM new pools on chain | trading-evm `evm-1` (record-only, 7 days) | On-chain capture at block speed with sales at fixed ages | A design that passes the design gate on evm-1's capture, for a group scout-2 calls GO |
| Meteora DBC graduates | trading-scout FEAT-104 | +7.4% a trade on 59 in scout-1's re-reading; creator liquidity can be locked | Whether locked liquidity dumps less, on an on-chain capture |
| Polymarket intraday weather and Fed | trading-polymarket paper runs | Stage 0 INCONCLUSIVE (data- and sample-limited) | Each lane's own Stage 1 verdict |
| Crypto Up/Down stale quotes after a spot move | trading-polymarket FEAT-147 | Cheap asks left stale by a Binance move are lifted within a second, an edge minute data cannot see (it was on §6 as "latency trades: an artefact of minute data" until 2026-11-04). In fill time it is gone within a second: the pre-registered rule loses in-sample once the data API's 2.2 s lag is removed. Part 1 (2026-11-07): we are fast enough for 89.9% of signals | The pre-registered rule on the fresh window 4–17 Nov, `--timestamp-offset 2.20`, from 18 Nov |
| Learning under a frozen rule (FEAT-105 selector, FEAT-106 crash model) | trading-pump, for any reopened lane | Adaptive rules cut losses | Walk-forward beats the best fixed rule on every capture |
| DAMM v2 pools by creator (added 2026-11-07) | trading-meteora `damm-2`, a dated exploratory check | damm-1: creators of 100+ pools drained 57% within 1 h, one-off creators 18% (crash rates, not trades; §3.4) | damm-2's split on positions in both halves, then a pre-registered fresh capture |
| Rug calls seen pending on EVM (added 2026-11-07) | trading-evm FEAT-172, `trading-evm mempool` | No on-chain warning before a pull (§3.4), so a pending pull is the only early sign left; outside bots claim 80–85% on Ethereum and BSC, where the public mempool is shrinking | A 24 h record on BSC, only if a BSC arm of evm-1 is GO: the share of pulls seen pending and how early |
| Shorts before large token unlocks (added 2026-11-07) | Not built | Keyrock: about 90% of 16,000+ unlocks came with selling from about 30 days before, team unlocks worst; `listings-1` (§3.6) tested listing dates only | A pre-registered Stage 0 study on an unlock calendar with intraday prices and funding, after an access check |

## 8. The strategy library

So that a venue can be tested against every strategy without rewriting one,
the venue-neutral strategies move into trading-core as a library
(trading-core ADR-011, `docs/STRATEGY-LIBRARY.md`; built 2026-11-03 for
trading-core's next release, calibration on trading-pump's captures still
open). Every library rule is generic: a result on Pump.fun or PumpSwap
describes those venues' traders, not the rule, so a NO-GO there does not
retire it on another venue. A module translates its data into four records (listings,
price readings, trade prints, holder snapshots); each strategy is a rule
class registered by name; a lane is composed in the settings file from one
entry rule, any gates, its exits and its limits; and a sweep replays a
venue's captures against every rule its data can feed and shortlists what
passes the design gate. A module can contribute its own rules the same way,
and a rule that needs only the four records can be promoted to the core.

| Strategy tried here | Library feature | Needs |
|---|---|---|
| PumpSwap momentum and instant lanes (FEAT-76, FEAT-78) | FEAT-120 `listing_momentum` | readings |
| Launch sniping, buying at the migration, new pools at the first reading | FEAT-121 `buy_at_listing` | readings |
| Fill-drift guard, lane slippage caps | FEAT-128 | readings |
| Pullback (FEAT-59) | FEAT-122 `pullback` | readings |
| Pre-graduation (FEAT-53) | FEAT-123 `curve_progress` | progress |
| Confirmed momentum (FEAT-51, FEAT-52) | FEAT-124 `demand_confirmation` | trades |
| Order-flow filters (FEAT-56, FEAT-57, FEAT-60) | FEAT-125 | trades |
| Holder and bundle screens, the supply map (FEAT-61, FEAT-96) | FEAT-126 | holders |
| Creator book, funders, reused names (FEAT-55, FEAT-63, FEAT-98) | FEAT-127 | creator, funder, name |
| Adaptive take-profit (FEAT-97) | FEAT-129 | readings |
| Trend rule (FEAT-65) | FEAT-131 `bar_trend` | readings |
| Adaptive gate and exit selector (FEAT-105) | FEAT-130 | readings |
| Stop arming and demand-hold variants | FEAT-132 | readings, trades |
| Crash model (FEAT-106) | FEAT-134 | holders, creator |
| Capital rotation (FEAT-24) | FEAT-135 | readings |
| Copy trading (FEAT-54) | FEAT-136 `wallet_follow` | trades |
| Take-profit tiers, stall exit, trading hours, a lane's own exits, break-even reporting | FEAT-92 to FEAT-95, FEAT-116 (built) | — |
| Polymarket's Fed and crossvenue lanes (a price against a reference) | FEAT-137 `reference_gap` | readings, reference |
| Polymarket's favourite–longshot and weather lanes (a probability band) | FEAT-138 `probability_band` | readings, resolution, outcome |

`trading-core-lanes list` prints the library; `trading-core-lanes sweep`
runs a venue's captures (converted to the records by its module:
`trading-pump lane-rows`, trading-evm's `lane-rows`) against it.

> [!WARNING]
> Testing a venue against every rule and variant will always find something
> that looks good by chance: about 240 variants on rc.9 chose the instant
> lane, which then lost on rc.11. The sweep only **shortlists** (positive on
> every capture at the base cost, not negative at the stress cost, above a
> random cut, with the number of combinations tried shown); only a
> pre-registered counted run on fresh data decides.

## 9. History of this page

- 2026-11-03: written from the results logs and run records of
  trading-pump (pumpfun-trading's included), trading-scout, trading-evm,
  trading-polymarket and trading-core, and the project's studies of
  2026-10-30 to 11-03; copied into every repository.
- 2026-11-03: every number checked against its source by a separate
  reader before the first copy; 22 corrections and 5 missing items made
  then.
- 2026-11-03: §6 gains a scope column (everywhere, or the venue where it
  failed) and a library column; §8 maps every strategy tried to the
  strategy library proposed in trading-core (ADR-011).
- 2026-11-03: §8: the library is built in trading-core (unreleased); the
  creator family's needs split (creator, funder, name); polymarket's lanes
  mapped to the proposed outcome-market rules (FEAT-137, FEAT-138).
- 2026-11-03: §8: FEAT-137 and FEAT-138 built in trading-core
  (unreleased).
- 2026-11-04: §3.5 and §6: crypto Up/Down late longshot (trading-polymarket
  FEAT-146) NO-GO on every taker trade of 30 days; FEAT-103's prior
  lowered.
- 2026-11-04: §6 "Crypto Up/Down latency trades" (Everywhere) taken off:
  it was judged on minute data and 45 minutes of ticks, and second-level
  prints show a 2–5 s edge after a spot move. Now a §3.5 row and a §7 lead
  (FEAT-147).
- 2026-11-04: FEAT-147 corrected: the data API's trade times run 2.2 s
  after the fill, so the "2–5 s" edge is under a second in fill time, and
  the rule loses in-sample once corrected (§1, §3.5, §7).
- 2026-11-07: §3.5 and §6: the crypto Up/Down expiry fade (trading-polymarket
  FEAT-103) NO-GO on FEAT-146's 30 days (−8.0% on stake; the mirror −1.4%).
  ADR-012 accepted: verdicts that scale with the evidence are built into
  `trading-core-audit verdict`.
- 2026-11-07: §3.5 sports across venues: the listing-time recorder
  (trading-polymarket FEAT-168) built and its run `sports-1` pre-registered.
- 2026-11-07: §3.5: the full-set scanner (trading-polymarket FEAT-102) built
  and its run `arb-1` pre-registered; binary pairs dropped (mirrored books).
- 2026-11-07: §1, §3.5, §6, §7: three days of `ticks` read out
  (trading-polymarket RESULTS §2): FEAT-147 part 1 takeable, so its rule
  runs on 4–17 Nov from 18 Nov; the crypto Up/Down maker (FEAT-101) NO-GO
  at our speed, and quoting at the top of those books added to §6.
- 2026-11-07: §3.4, §3.6 and §6: the rug-strategy backtests (project note
  `claude/rug-backtests-2026-11-07.md`): locked-liquidity launchpads,
  liquidity custody and the EVM precursor tripwire on scout-2, DAMM v2 pools
  by creator on damm-1, and study `listings-1` (FEAT-173, NO LEAD).
- 2026-11-07: §7: three leads from the rug-strategy work (DAMM v2 pools by
  creator, rug calls seen pending on EVM, shorts before token unlocks).
- 2026-11-08: §3.5: the steady-winners study on FEAT-146's backfill
  (trading-polymarket RESULTS, 2026-11-08): NO LEAD.
