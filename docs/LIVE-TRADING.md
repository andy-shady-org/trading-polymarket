# Live trading

**Live execution is deliberately not built in 0.2.1.** With `"mode": "live"`
and `--live`, the module refuses every order and the balance read with
`ExecutionRefused`, so trading-core keeps entries blocked. Nothing in this
repository holds or needs a key ([`ENVIRONMENT.md`](ENVIRONMENT.md)).

Live execution is built only when a lane has passed Stage 1, and is itself
gated like a release ([`dev/RELEASE-GATE.md` §3](dev/RELEASE-GATE.md#3-capital-gate);
ADR-007 in [`dev/ARCHITECTURE-DECISIONS.md`](dev/ARCHITECTURE-DECISIONS.md)).
Where each lane stands: [`dev/RELEASE-GATE.md` §1](dev/RELEASE-GATE.md#1-current-status).

This page is the plan for that work.

## 1. What it needs

| Piece | Detail |
|---|---|
| Client | `py-clob-client-v2` (CLOB V2, live since 28 April 2026), as an optional extra (`pip install -e .[live]`), so paper installs stay dependency-free |
| Collateral | pUSD (CLOB V2 collateral) in a Polymarket proxy wallet; allowances set once |
| Keys | Private key and CLOB API credentials from environment variables only (`TRADING_PM_PRIVATE_KEY`, `TRADING_PM_API_KEY`, …, [`ENVIRONMENT.md` §3](ENVIRONMENT.md#3-planned-for-live-trading-not-read-yet)), never in settings files; masked by trading-core's redaction |
| Orders | FOK or FAK limit orders at the analyst's limit price, sized in shares, tick and minimum size from the market; a partial fill is reported as such |
| Fills and costs | Read back from the CLOB trade (price, size, fee) → `TradeCosts(source="venue")` |
| Balance | pUSD balance from the CLOB (`get_balance`); trading-core blocks entries until the first read succeeds |
| Settlement | Redeem resolved positions (neg-risk adapter for neg-risk markets); record the redemption as the sell at 1 or 0 |
| Reconciliation | Daily: wallet pUSD delta vs audit net, within max($1, 5%) ([`dev/RELEASE-GATE.md` §3.5](dev/RELEASE-GATE.md#35-stage-2--live-canary)) |

## 2. The contract stays the same

`PolymarketModule.execute(order, paper=False)` dispatches to `LiveExecutor`;
replacing its body is the whole change on the module side. The paper
executor's rules (no fill without a fresh book, the limit is a hard limit,
shares rounded down, minimum size) are the specification the live executor
must match — a paper fill must never succeed where a live one would not.

## 3. Before the first live order

- [ ] A lane has a Stage 1 GO
- [ ] Live executor implemented with tests at 100% (fake CLOB client)
- [ ] One round trip at $1 by hand-run script, reconciled against the wallet
- [ ] `configs/live.example.json` copied with one lane enabled and `max_notional` ≤ 5
- [ ] Dedicated wallet funded with only what can be lost entirely
