# Lessons

Every lesson the project has paid for, from every repository, in one place.
Each repository's `AGENTS.md` keeps its own learnings log in the words of the
incident; this page collects them across repositories, removes duplicates,
and says what each one means for a new module, chain or venue. The
companion page, [`STRATEGY-LEDGER.md`](STRATEGY-LEDGER.md), records every
strategy tried and its result.

> [!NOTE]
> **This page is shared.** The master copy is trading-core's
> `docs/LESSONS.md`. Every repository built on trading-core carries an
> identical copy at `docs/LESSONS.md` (trading-core's
> `docs/dev/DOCUMENTATION.md` §2.4). Change it in trading-core, then copy it
> unchanged to every repository; never edit a copy.

**How to read an entry.** The rule in bold, then what it means, then where
it was learned: the repository, the bug or result ID, and the date. IDs are
the source repository's (`BUG-` and `FEAT-` from trading-pump unless named;
`TC-` from trading-core; `SC-` from trading-scout). Every entry applies to
every module unless it says otherwise.

Contents: [1. Strategy and evidence](#1-strategy-and-evidence) ·
[2. Know the market before building](#2-know-the-market-before-building) ·
[3. Paper, replay and parity](#3-paper-replay-and-parity) ·
[4. Costs and execution](#4-costs-and-execution) ·
[5. Risk and the engine](#5-risk-and-the-engine) ·
[6. Data providers and RPC](#6-data-providers-and-rpc) ·
[7. Streams](#7-streams) · [8. Runs and operations](#8-runs-and-operations) ·
[9. Security](#9-security) · [10. Tests and tools](#10-tests-and-tools) ·
[11. Documents and history](#11-documents-and-history) ·
[12. History of this page](#12-history-of-this-page)

## 1. Strategy and evidence

The lessons that decided four weeks of results. Read these before proposing
any lane.

1. **Income path first.** A lane must show net income after every cost
   before anything is built on it. Report profit net of fees, priority
   fees, tips and rent; judge every run by a pre-registered verdict.
   *(trading-pump norm, from pumpfun-trading.)*
2. **Pre-register the verdict.** A run is evidence only when the rule that
   judges it, the config and the code were fixed and hashed (sha256) before
   it started. Never change a counted run while it runs, and never tune a
   lane on the run that judges it. *(trading-core; every counted run since
   rc.9.)*
3. **Beat a random cut.** Every filter on a losing lane "improves" net PnL
   because it trades less. Compare a filter's kept net with the same share
   of the total chosen at random, on at least two captures, before calling
   it an edge (`trading-core-audit cuts`). *(trading-pump RESULTS §6.6:
   the FEAT-57 wash filters helped on v0.2.3 and not on rc.1; §6.5 and
   §6.11: FEAT-56 beat a random cut on two captures, and the combination
   fell below one on rc.3.)*
4. **Design on old data, judge on new.** Pick a rule on captures that
   already exist; judge it on a run that has not happened yet. A rule picked
   after seeing the data it is reported on is not evidence. *(trading-pump
   §6.3: the 8-buyer rule looked positive in-sample and failed out of
   sample, §6.4.)*
5. **Choose for the worst case.** A candidate must be positive on every
   design capture on its own at the base cost and not negative at a stress
   cost; among those, the best **worst** capture wins (maximin), never the
   best pooled total. *(trading-pump PUMP-12-PLAN §2; it rejected all 61
   exit rules and 105 entry variants in §6.20.)*
6. **Only test what could be a GO.** Before proposing a run, show that some
   design passes the pre-registered gate on the data in hand. A gate that
   only cuts losses is not a design, and a record-only week that repeats
   data already held teaches nothing. *(Operator correction, 2026-11-03:
   pump-12 was stopped before it started.)*
7. **Look for the trade, keep the gate.** The job is to find rules that make
   money. Lead a read-out with the best variant, its trade count and its
   risks; let the pre-registered verdict and the out-of-sample run do the
   rejecting, not the tone of the read-out. *(Operator correction,
   2026-10-30.)*
8. **Demand before entry.** A position with no buyers after it cannot be
   saved by any exit. Never buy a launch without evidence of follow-on
   demand. *(pumpfun-trading v0.2.3: −0.579 SOL over 1,675 launch buys,
   10.3% won.)*
9. **Charts show survivors.** Coins seen on charts and trending lists are
   the ones that survived. Before building for a pattern seen on a chart,
   measure how often it happens across every coin it could have happened
   to. *(trading-pump FEAT-73, 2026-10-26: of 39 fast graduates that fell
   below half their graduation price within 15 minutes, none recovered.)*
10. **Judge on what was known at entry.** A "passed" that needs every later
    check clean keeps only the pools that survived and flatters every group.
    Pre-register on what the buyer could know at the moment of the buy;
    count later failures as traps and a rug while held as a total loss.
    *(trading-scout scout-1 read-out, 2026-11-02, and scout-2, 2026-11-03.)*
11. **Count the funnel before tuning the edge.** Before tuning a lane's
    exits, count where the population drops out (not a candidate, filtered,
    refused by slippage, refused by risk) and replay each excluded group as
    a lane of its own. *(trading-pump §6.18: rc.10 bought 7 of 310
    graduates; the excluded instant graduates were the best group in the
    replay.)*
12. **A crash predictor is not a trade filter.** A feature that predicts a
    bad outcome can still be useless as a filter if the same coins are also
    the best trades before the bad outcome. Judge a filter on the lane's
    result per trade on every capture, never on the outcome it predicts.
    *(trading-pump §6.21, the supply map: bundled coins crash more and pump
    higher first.)*
13. **Score the copy, not the wallet.** A wallet's own record is not what
    copying it earns: the copier buys later, at a worse price, and can be
    sold into. Rank a wallet only on the simulated net of copying it at the
    module's own delay and costs, on a second capture, and check it is not a
    creator. *(trading-pump §6.8: copying every captured wallet lost
    ~0.0013 SOL a copy; the "successful" wallet was a serial creator.)*
14. **Read results per position, never per sell.** Win rate and expectancy
    are per closed position, with the buy's costs booked on it. *(BUG-105:
    per-sell rates turned flat exits into wins.)*
15. **A paper result far above its costs is a bug until explained.**
    *(BUG-104: +63.5 SOL of "profit" was a pricing artefact; BUG-145: 29% of
    rc.5's buys, all of its profit, were fallback fills.)*
16. **Regimes move edges.** An edge that is other traders' behaviour (launch
    bots, operators' pumps) can halve within a day. Report a lane per
    capture and per half, and expect its size to change. *(trading-pump
    §6.19: the instant lane's pump height fell from a median 2.3× to 1.3×
    between two days; the lane went from +18.6% to −20.7% a trade.)*
17. **A time-of-day or weekday effect needs two captures.** Every hour and
    weekday split so far changed sign between captures. *(trading-pump
    §6.10, §6.20 A4.)*
18. **Learn only under a frozen rule.** A learner (an adaptive target, a
    rule selector, a model) may run in a counted run only if the learning
    rule itself is frozen and pre-registered, and it is judged walk-forward
    against the best fixed rule chosen in advance. *(trading-pump ADR-010,
    §6.21: the adaptive gate cut losses and still failed the design gate.)*
19. **Size the run to reach its verdict.** A counted run that cannot reach
    its minimum count in its length is wasted. Estimate positions per day
    from replay first. *(trading-pump §6.19: rc.9 made about a position an
    hour and stopped at 55 of 100.)*
20. **Score probabilities, not just PnL.** A few hundred binary trades are
    mostly noise. Where a lane prices an outcome, compare the model's Brier
    score with the market's on every priced bucket: no Brier edge, no edge,
    whatever the PnL says. *(trading-polymarket: the day-ahead weather model
    0.067 against the market's 0.057.)*
21. **Know where the PnL comes from.** Split a result by how it was made
    before trusting it. *(trading-polymarket Fed lane: +$25.08 selling into
    convergence, −$2.51 holding the same entries to resolution.)*
22. **A few big wins are not an edge.** Trust the "without the best"
    check, the bootstrap interval and a held-out window; do not assume a
    bias from the literature holds on this venue. *(trading-polymarket:
    favourite backtest +$537 on 435 trades, carried by five longshots; the
    full out-of-sample window lost $147.)*
23. **Too good to be true is a bug.** An edge far above what the market
    allows is a model error until explained; cap it (`max_edge`) and blend
    towards the market. *(trading-polymarket TP-1: "55 points of edge" from
    an uncorrected forecast grid.)*
24. **Measure the model on the exact question traded.** A model that looks
    fine on average can be badly off on the one question a lane bets on.
    *(trading-polymarket TP-11: no better than the market on Brier, and off
    by about 5× (0.34 against 0.07) on the one question it bet, "the
    maximum still rises after 15:00".)*
25. **Correlated bets are one bet.** Positions that settle on the same
    outcome or thesis are sized as one; Kelly assumes independence.
    *(trading-polymarket TP-12: ten quarter-Kelly bets on one thesis were
    about 2.5× full Kelly.)*
26. **Waiting for a feature is not filtering on it.** A rule that waits for
    a condition enters later and higher, which can remove the gain the
    condition showed among existing entries. *(trading-pump §6.4: positions
    that already had 8 buyers did well; waiting for 8 buyers lost.)*
27. **Judge a win rate against its break-even win rate.** A lower target
    raises both. *(trading-pump rc.11-tp20: 42% → 63% won on the same coins,
    break-even 68%, still a loss.)*
28. **Do not cap the right tail that pays for the stops** unless the data
    says so, per venue. *(Pump.fun curve momentum: the profit was a few coins
    past +50%, and +20–30% targets were worse; on PumpSwap instant coins a
    lower target lost less. Measure it each time.)*
29. **Design-document numbers are not evidence.** Win rates, payoff ratios,
    Sharpe targets and Kelly inputs written in a plan were never measured;
    only results logs are evidence. *(pumpfun-trading `STRATEGY.md`'s "p_win
    0.35 to 0.45" was never measured; measured win rates ran from 5.9% to
    71%, and what decided results was the break-even win rate, 37–68% on
    PumpSwap.)*
30. **One day is too little data.** A small edge per position cannot be
    told from noise, or from the hour, in a day; plan captures of 48 h or
    more and counts of 100 positions or more. *(pumpfun-trading RUNBOOK
    §6.3.)*
31. **Do not loosen the breaker or the screen to get more trades.** Fix the
    cause of the losses instead. *(v0.2.1 pilot; rc.3: relaxed caps buy
    insider pumps.)*
32. **A wallet's win rate is not a copyable edge:** a wide scan always
    finds lucky wallets, many top scorers are snipers, insiders or wash
    bots, and a wallet known to be copied can sell into its copiers.
    *(pumpfun-trading FEAT-54.)*
33. **Replay a winning wallet's pattern on every market, not its picks.**
    Its record is the rule plus its selection and its luck; only the rule
    on the whole population says whether there is an edge to take.
    *(trading-polymarket FEAT-146: `@vega7` made +$33.7K buying Up/Down
    sides under 5 c late in the window; the same rule on all 8,615 markets
    of 30 days lost 16.9%.)*

## 2. Know the market before building

1. **Record the population, not the selection.** Sample the whole
   population from its first event and keep following each exit for a
   while, record-only and off every decision path, or ideas raised later
   cannot be tested on the capture. *(trading-pump FEAT-72, 2026-10-24: rc.3
   followed only the 14% of launches its screen passed.)*
2. **Observe without touching.** Record-only data never reaches a watch
   list, a signal, a shadow book or a fill; it is polled in its own task,
   tagged, and skipped by replay. *(trading-pump, rc.3 observation rows.)*
3. **Count a chain's pool kinds before its screen.** Sample new pools by dex
   before a run; build the missing check first when the group the run is
   about is among the unsupported. *(trading-scout, 2026-11-03: 83% of
   Robinhood Chain's new pools were Uniswap v4 or Pons curves.)*
4. **A price list is not a cost; only a sale is.** Lists and charts do not
   show launch fees, sale taxes, blocked sales or empty pools. No return on
   a new chain is trusted until a simulated sale shows the price was
   executable. *(trading-pump §6.13; trading-scout §1: three of five Meteora DAMM v2
   launch round trips lost 92–99.9% (the others 0.6% and 4.8%) where the
   list showed an ordinary price.)*
5. **An empty pool is not a price.** Many new Uniswap v4 pools hold no
   liquidity in range and many new v2 pairs have no reserves in their first
   minutes; lists still show reserves and volume. Read the pool's own state
   before trusting a number about it, and report a check on an empty pool
   as an error, never as the token refusing a sale: on scout-2 most v4
   "failures" were launch positions withdrawn minutes after creation (a
   pulled pool traps a buyer; it says nothing about the token's code).
   *(trading-scout FEAT-84, SC-7; trading-evm 0.1.0 live checks.)*
6. **A pool smaller than the trade has no price.** Record the pool's native
   depth with every check and flag a pair under 10× the trade as thin.
   *(trading-scout SC-2: pairs valued at $55,000 held 0.0001 BNB.)*
7. **On EVM chains a sale that worked can stop working.** An owner can
   switch on a tax or a block after launch: simulate a sale before every
   exit, not once at entry. *(trading-scout scout-1: 94% (BSC) and 83% (Base)
   of pools clean at the first check were not at the last.)*
8. **Two quotes are not a trade.** A round trip from two quotes seconds
   apart can come back above what it spent; that is `inconsistent`, never
   `passed`. *(trading-scout.)*
9. **Trust the program, not the feed.** A launch feed carries other
   launchpads and other tokens; buy only what the venue's own program owns
   and reads as standard. *(BUG-108: 263 non-Pump.fun mints bought,
   USDC among them.)*
10. **New accounts arrive late.** A missing account right after a create is
    "not yet", not "never": wait a bounded time, measure the wait, and check
    that what a refusal filters out is not the better half. *(BUG-154: 80%
    of rc.6 buys refused; the skipped coins did better.)*
11. **Date an account by its history, not by when a stream showed it.**
    *(trading-pump FEAT-80: a pool subscription fired on every swap, so
    "first seen" did not mean new.)*
12. **Measure a subscription's volume before designing on it.**
    *(FEAT-80: 47 messages, 36 kB a second for 832 pools.)*
13. **Stream payloads are not enrichment.** A create event carries no
    socials or holders; enrich with bounded timeouts, off the hot path.
    *(BUG-95.)*
14. **Empty is not zero.** An index-backed answer that is empty for a new
    token is "not indexed yet"; retry inside the lookup budget and never
    score it as "no holders". *(BUG-107: 67% of Stage 0 buys showed no
    holders.)*
15. **Read the rules of each market.** The settlement source and rule
    decide whether a model applies; the same title on two venues can be a
    different bet. Pair markets on their rules and check both settled alike
    before trusting a replay. *(trading-polymarket TP-2: weather events
    settled on non-METAR sources; RESULTS 2026-10-29: a Fed duplicate
    resolved "No change" while the Fed hiked.)*
16. **A feed's event type is not a clean population.** Only about 40% of
    PumpPortal's migration events were standard graduations; filter by what
    the chain shows (pool SOL, price), not by the event's name.
    *(pumpfun-trading FEAT-76.)*
17. **Say when a quantity cannot be observed** from your data, rather than
    proxying it silently. *(pumpfun-trading: first recorded trades came
    more than 3.3 s after the create for 90% of mints, so first-slot
    snipers were never seen; trade messages carried no slot.)*
18. **A count stuck on a round number is probably a page cap.**
    *(pumpfun-trading v0.2.0: serial-launcher rejections at exactly 20
    tokens.)*
19. **A filter whose input nobody fills is dead code.** Check the input is
    populated before counting on the filter. *(`creator_rugs` was 0 on all
    24,521 screening records; the sybil detector never had `funding_links`.)*
20. **Check that a borrowed rule can fire on your entries.** *(A "fell 60%"
    rule fired on 2 of 1,229 tokens: a fresh curve cannot fall that far below
    a ~30 SOL entry.)*
21. **Empty is not collected.** Store only records that hold the data the
    replay needs, and check coverage per period. *(trading-polymarket TP-4:
    1,190 events stored with empty price series.)*
22. **A NO-GO holds only at the resolution it was measured at.** An edge
    that lasts seconds is invisible in minute data; before putting an idea
    on "do not test again", say what resolution judged it, and judge speed
    edges on ticks. *(trading-polymarket FEAT-147: Up/Down "latency trades"
    were closed on minute data; second-level prints showed cheap asks lifted
    within a second of a spot move, +163% a trade where spot and fill
    coincide.)*

## 3. Paper, replay and parity

1. **Model the latency you pay.** Every paper execution setting (entry
   delay, slippage, exit slippage) is modelled in replay too, through config
   keys both read. *(BUG-121: replay beat paper by 0.016 SOL and made an
   8-buyer variant look profitable.)*
2. **Model the exit too.** Paper sells pay the same latency and impact as
   live sells. *(BUG-126: paper was about 1% an exit too kind; +0.014 SOL
   became about −0.007.)*
3. **No read, no fill.** A paper fill fails whenever the live one would (no
   read, a closed or complete pool, a zero quote); never add a fallback
   price to any fill or exit, and count refusals. *(BUG-145, BUG-146,
   BUG-152.)*
4. **One price source for entry and exit.** *(BUG-104: entries from the
   stream's market cap, exits from the chain.)*
5. **Replay cannot see what it did not record.** Rules that act on the fill
   price are judged on paper captures, not replay sweeps, unless the capture
   records the fill's own read. *(trading-pump §6.4; BUG-164: the replay
   filled momentum buys at the signal's own reading, 2.1% off at the
   median.)*
6. **Check replay parity before trusting a sweep.** Replay a run's own
   capture and compare positions, exits and net with the run; explain every
   gap first, and re-run sweeps after any replay fix. *(trading-pump §6.3,
   §6.20 A2.)*
7. **Tick faster than the cycle.** A replay advances by the smaller of the
   feed's interval and the engine's cycle, so both get their turn.
   *(trading-pump 0.4.0; trading-core FEAT-110's `run_replay`.)*
8. **A replay never looks ahead,** except a fill's bounded look-ahead to the
   reading the live order would have read. *(trading-core `TimeIndex`.)*
9. **Scanned and simulated nets are relative.** An offline simulator that
   fills at recorded prices is compared only with its own baseline;
   calibrate it against a real run's trades, per lane, before trusting it.
   *(trading-pump §6.9; §6.20's simulator matched 242 of 245 rc.11 instant
   trades in sign, but gave −0.2% a trade on rc.9's momentum lane where the
   engine replay gave +5.9%, a gap never explained: re-check it before any
   momentum design rests on that simulator.)*
10. **Paper is not live.** Live adds landing delay, failed sends and
    sandwiches; Stage 2 is where they show, at the smallest size.
    *(trading-pump PUMP-12-PLAN §8.)*
11. **Re-check on the live book.** A scout's or list's price is a
    prefilter; apply every band and guard again on the live book before the
    fill. *(trading-polymarket TP-6.)*
12. **Parity proves nothing when both sides read the same wrong price.**
    Check prices against an independent source too. *(v0.2.0: replay and
    paper agreed on 986 exits of a +63.5 SOL artefact.)*
13. **Replay models the breaker the run had.** *(FEAT-66: a halted paper
    day showed as a false 93-position parity gap.)*
14. **Quote both legs of a round trip together,** or judge on the
    distribution: a gap between the legs puts the price move into the cost.
    *(BUG-139.)*
15. **The signal source is not the cost source.** Exchange bars can drive a
    signal; costs come from quotes on the venue that fills. *(FEAT-65.)*
16. **Paper is never cheaper than live.** An unknown fee is charged at the
    highest rate, never zero. *(trading-polymarket norm.)*
17. **A replay uses only prints the rule could have traded in time.** A
    market can keep trading after its outcome is all but known: crypto
    Up/Down markets print for a minute or so after the window closes, with
    the losing side near zero. Cut a replay at the close (and at a rule's
    own deadline). *(trading-polymarket FEAT-146: about 1,200 prints a day
    after the close, 110 of them cheap buys.)*
18. **Know what a timestamp measures before you lag anything by it.** A
    venue's trade time can be its settlement, not its fill: measure the
    offset against the fill's own feed before timing a reaction from it.
    *(trading-polymarket FEAT-147: the data API's times run 2.2 s after the
    fill; a "2 s" reaction was really instant, and the rule built on it lost
    once corrected.)*

## 4. Costs and execution

1. **Measure the fee from real swaps.** Decode real trades of the
   population and check the module's maths reproduces them before trusting
   a cost assumption; use the token's real supply where a fee tier depends
   on it. *(trading-pump §6.16, BUG-162: 92 of 94 trades matched; burns had
   lowered one mint's supply 3.8%.)*
2. **Know the break-even before the target.** With a round trip of c, a
   take-profit below about c (plus haircuts) cannot pay; a lower target
   raises the win rate and the break-even win rate together. *(trading-pump
   §6.20 A3/A4: PumpSwap round trip 2.4%; nothing below +3.2% pays.)*
3. **Stops gap through.** A stop fills where the next reading is, not at
   its level: measure the fill against the stop on real paths. *(Pump.fun
   curve: −19% median on a −15% stop; PumpSwap instant graduates: −44%
   median, because the dump is one slot of about 20 identical sells.)*
4. **Faster reads do not fix a one-slot dump.** *(trading-pump §6.20: 160
   of 171 instant stops came on 2 s reads and still filled at −33%.)*
5. **A larger order changes nothing but risk** when the fee is a share of
   the order. *(PUMP-12-PLAN, "Not in pump-12".)* Measure it by size, though:
   on PumpSwap's momentum lane the fixed part was 0.35% of a 0.02 SOL round
   trip; 0.05–0.1 SOL recovered 0.15 points, and above 0.3 SOL the pools'
   depth (about 100 SOL) cost more than that. *(2026-11-04 size re-check,
   ADR-012.)*
6. **Close what you open.** Every buy that opens an account pays rent; a
   full exit closes it, and every trade record carries its fees, tip and
   rent. *(BUG-96.)*
7. **Do not hard-code rent or fees;** take live costs from the transaction.
   *(Token-2022 ATA rent was lowered to 1,513,840 lamports.)*
8. **Fees hide in launch windows.** Meteora DAMM v2 charges an anti-sniper
   fee that starts near 100% and decays; read the fee at each moment from
   the pool. *(trading-scout smoke runs, 2026-10-30.)*
9. **Gas is not the obstacle at a few dollars a trade on BSC and Base
   today,** but check it per run: two swaps were about 0.3% of 0.005 BNB at
   0.05 gwei. *(trading-scout §1.)*
10. **Sell what you delivered.** A round trip cheaper than the pool's own
    fee is a bug until explained. *(trading-scout SC-1.)*
11. **Size fixed per-transaction costs to the position.** *(Two
    300,000-lamport tips were 6% of a 0.01 SOL position; tips were 83% of the
    listed costs at 0.01 SOL.)*
12. **Pay for fast exits before fast entries.** A late entry costs a
    skipped buy (the drift guard); a late stop sells lower. *(pumpfun-trading
    RUNBOOK §6.3; the tip experiment that would test it was never run.)*
13. **The tip is the last instruction of the transaction.** *(Solana, Jito;
    trading-solana.)*

## 5. Risk and the engine

1. **The module owns the venue, the core owns the run.** Sizing, risk, the
   breaker, exits, accounting, persistence and alerts are trading-core's;
   never re-implement them in a module. If the contract cannot express
   something, change trading-core with its own test.
2. **A limit nobody checks is not a limit.** Every documented risk limit has
   a test that trips it; locks outlast the daily rollover; a cumulative cap
   only the operator resets. *(BUG-127, BUG-128.)*
3. **A ratchet only moves up,** built from a persisted running peak.
   *(BUG-141.)*
4. **Size risk triggers to the account.** *(BUG-144: +0.5% realized and a
   0.04% dip halted a day.)*
5. **Locks starve a paper sample too.** Size the paper wallet so a normal
    losing streak does not reach the daily lock, and report the hours
    locked with the verdict. *(v0.2.1: a 10% lock on 0.25 SOL was about 37
    flat round trips, reached in an hour; rc.11 was locked 27 of 72 h.)*
6. **A profit ratchet starves a paper sample.** A paper run that must reach
   a count uses the `"baseline"` drawdown reference; the ratchet is a
   live-capital choice. *(trading-pump §6.18: 126 positions instead of
   191.)*
7. **Every lane needs its own limits** (budget, exposure, pause), checked
   after the portfolio gate. *(trading-core FEAT-81.)*
8. **Lane exits need empty engine exits.** If a lane runs its own exits, the
   engine's `exits` are `{}` or they fire first. *(trading-pump FEAT-79.)*
9. **Value equity at what a sale returns,** never at a mark. *(BUG-136.)*
10. **Real numbers only.** Price live entries from the fill; never let a
   placeholder (a default price, a simulated balance) reach a decision.
   *(BUG-129, BUG-130, BUG-158.)*
11. **Fail closed, never guess.** A failed read makes the quote stale and
    the fill refused. *(trading-pump norm.)*
12. **Re-check under the lock.** Anything that waited for a lock re-validates
    its precondition. *(BUG-140.)*
13. **Compare thresholds with tolerance.** *(TC-1: a position down exactly
    20% held through a 20% stop.)*
14. **Check limits against size.** When a config changes the order size or
    the exposure, check every inherited cap still admits one position.
    *(pumpfun-trading: the first momentum replay bought nothing.)*
15. **Tell the module what only the engine knows,** explicitly.
    *(trading-core: `CLOSES_POSITION`.)*
16. **A one-sided book is worth what its bids pay.** Value a position by
    walking its own bids, 0 if none, never at the last trade. *(trading-polymarket
    TP-5: a phantom $3,725 peak tripped the breaker.)*
17. **Feed health must not depend on holding.** Report health from a
    heartbeat read, not only when a position is quoted. *(trading-polymarket
    TP-10: flat runs went stale and stopped reading.)*

## 6. Data providers and RPC

1. **Probe free APIs and public endpoints before picking defaults.** Check
   real limits by hand (rate, history depth, methods served, log ranges,
   address limits), write them next to the default, retry 429 and 5xx with
   bounded growing waits, and never trust a zero reset. *(Jupiter keyless 5
   requests per ~10 s; GeckoTerminal `Retry-After: 0`; publicnode BSC/Base
   logs need an address, at most 10.)*
2. **Check a plan's limits before recommending it.** *(A CoinGecko demo key
   was named as a fix; its history is also 365 days.)*
3. **One pool, several names.** Match providers on the token as a fallback,
   mark what was substituted, and check the miss rate per chain.
   *(trading-pump FEAT-74.)*
4. **An address-shaped id is not always an address.** *(SC-4: Uniswap v4
   pool ids.)*
5. **An error is not an empty answer.** Raise on an RPC `error` or a missing
   result; never default to empty. *(BUG-159.)*
6. **Check the network, not just the URL.** Verify the chain (genesis hash,
   chain id) at start. *(BUG-160: a devnet URL answered mainnet reads with
   empty accounts.)*
7. **A load-balanced RPC is not one node.** End a log range at `"latest"`,
   and check every default serves every method the code calls.
   *(trading-scout FEAT-84.)*
8. **An open breaker sends nothing.** Fail fast while open, grow the
   cooldown, probe one at a time, stop buying with no endpoint, keep
   record-only reads off a rate-limited endpoint, one key per bot.
   *(BUG-151, BUG-149.)*
9. **Libraries ignore proxies by default.** Use `trust_env=True`.
   *(SC-3.)*
10. **Write the parent row first.** *(SC-5.)*
11. **Stamp readings by time, not block number,** on rollups.
    *(trading-evm: on Robinhood Chain `block.number` in a call is
    Ethereum's.)*
12. **Shared IPs share quotas.** A free allowance per IP is shared by
    everything on that host; cache, and run research where the quota is
    yours. *(trading-polymarket, Open-Meteo.)*
13. **Zero means refetch.** Freshness is `age < max_age`, so `max_age=0`
    always reads. *(trading-polymarket TP-3.)*

## 7. Streams

1. **Silence must reconnect:** pings and an idle timeout on every
   long-lived socket. *(BUG-150: a half-open socket waited 3 h.)*
2. **Check that subscriptions deliver,** and log every server message.
   *(BUG-112: positions held blind.)*
3. **A reconnect is not a fix;** close a feed breaker only on proof of
   delivery. *(BUG-116.)*
4. **Retry a refusal on a fresh connection.** *(BUG-156.)*
5. **Unsubscribe where positions close,** in the one function every exit
   goes through. *(BUG-120.)*
6. **No fake connections.** *(pumpfun-trading Geyser.)*

## 8. Runs and operations

1. **Smoke-test every new runtime against live data before a counted
   run.** *(BUG-159, BUG-160, SC-3 were all found that way.)*
2. **A cycle count is not a duration:** `trading-core run --run-for`.
   *(TC-11.)*
3. **One writer per file;** change every path when copying a settings
   file. *(TC-7.)*
4. **One retention policy per file;** after a long run, check the oldest
   capture row is near the start. *(BUG-157: the first 20 h of a 37 h run
   were lost.)*
5. **Rotate by on-disk name.** *(BUG-97.)*
6. **Never cancel a dequeued write.** *(BUG-103.)*
7. **A blocked exit is a warning,** with its cause, backed off and alerted
   once. *(BUG-148.)*
8. **The module logs too.** *(TC-6.)*
9. **Alerts are I/O.** *(BUG-110.)*
10. **Defaults are not choices.** An environment override beats a filled-in
    default. *(BUG-117.)*
11. **Unknown keys are errors; a documented variable must be read.**
    *(BUG-125, BUG-142.)*
12. **Validate what will run.** *(TC-5.)*
13. **Give every run its own runtime folder and set every path.**
    *(v0.2.3: a missing status path restored and sold an old position.)*
14. **Never change the code a running bot imports from;** branch work goes
    in a worktree with its own environment. *(pumpfun-trading RC4-HANDOFF.)*
15. **Stamp provenance on every run:** build, config and fee schedule, so
    results are comparable. *(FEAT-68.)*
16. **Never interrupt a running counted run or change a file it uses.**
    *(Standing operator rule.)*

## 9. Security

1. **Secrets live in the environment;** never in settings, logs, status
   files, alerts or commits. *(BUG-102, BUG-118.)*
2. **Redact before persisting:** every URL and string that may hold a key
   goes through `redact_text`. *(TC-2.)*
3. **Module text is data, not markup.** *(TC-8: a coin's name froze the
   dashboard.)*
4. **Run code on downloaded data in isolation** (`python -I`, its own
   folder). *(Standing rule.)*

## 10. Tests and tools

1. **100% statement and branch coverage on Python 3.11–3.14;** green on
   3.14 is not green on 3.11. *(TC-3 and trading-pump, 2026-10-28.)*
2. **No network, no ambient settings, no real alerts in tests.**
   *(BUG-143.)*
3. **Resolving a bug means tagging a test** (`regression("BUG-n")`).
4. **Moved code loses the tests that covered it by the way;** run coverage
   on the moved tests alone. *(trading-solana, 2026-11-03.)*
5. **A smaller suite needs an account** of every regression removed.
   *(trading-pump migration.)*
6. **No stash in a shared tree; one editor per file.**
7. **The Mac folder cannot delete;** deliver commits as bundles fetched
   into a branch, never state-changing git there.

## 11. Documents and history

1. **The code is the truth;** a documented default, key or status is
   checked against the code in the same commit.
2. **History is kept, not rewritten:** results, bugs, run records and this
   page are appended to; a correction is a new dated line.
3. **Completion claims track code.** Verify before ticking. *(pumpfun-trading
   TODO item 25.)*
4. **Rewrite links by path, not by anchor.**
5. **A feature's docs change in the commit that builds it, and its status
   changes when it ships.** The commit that builds a proposal moves it whole
   to `DONE.md` (a one-line pointer stays), lists it in `FEATURES.md`, sets
   its registry row in trading-core's `PROPOSED-FEATURES.md` and an ADR it
   carries out to Accepted; the tag and the install update `RELEASE-GATE.md`
   §1 and `TODO.md`; a shared page changed in trading-core is copied to every
   repository in the same change. Docs left for a later sweep drift.
   *(2026-11-07 sweep: trading-core ADR-011 still "Proposed" after 0.6.0
   built it; 52 built proposals across five repositories still listed as
   proposed; `RELEASE-GATE.md` pages calling tagged releases "to be
   tagged"; this page and `STRATEGY-LEDGER.md` three days behind trading-core
   in every copy.)*

## 12. History of this page

- 2026-11-03: written from the learnings logs of trading-pump (87 entries,
  pumpfun-trading's included), trading-core (33), trading-scout (13),
  trading-solana (17), trading-evm (3) and trading-polymarket, and the
  results logs; copied into every repository.
- 2026-11-03: every number checked against its source by a separate
  reader before the first copy; 22 corrections and 5 missing items made
  then.
- 2026-11-03: §5 lesson 5: an empty pool's check is an error, not a
  verdict on the token (trading-scout SC-7, from scout-2).
- 2026-11-04: §1 lesson 33 and §3 lesson 17, from trading-polymarket
  FEAT-146.
- 2026-11-04: §2 lesson 22, from trading-polymarket FEAT-147.
- 2026-11-04: §3 lesson 18, and §2 lesson 22's evidence corrected, from
  FEAT-147's first recording (the data API's 2.2 s lag).
- 2026-11-04: §4 lesson 5, the fixed cost measured by size on PumpSwap's
  momentum lane (ADR-012); this line added on 2026-11-07.
- 2026-11-07: §11 lesson 5, from the documentation sweep of every
  repository; the copies brought level with this page.
