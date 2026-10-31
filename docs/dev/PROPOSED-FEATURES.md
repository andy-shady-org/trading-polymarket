# Proposed features

Features of trading-polymarket that are not built, and why not yet. What is
built is in [`../FEATURES.md`](../FEATURES.md); open work on what exists is
in [`TODO.md`](TODO.md).

**IDs.** `FEAT-<n>` is one series shared by every repository, kept in
trading-core's `docs/dev/PROPOSED-FEATURES.md`: take the next free number
there and bump it in the same pull request. The ideas below were written
before that series reached this repository and **have no ID yet**; give one
an ID when work on it starts.

## 1. Ideas not built (and why)

Moved here on 2026-10-31 from `docs/STRATEGIES.md`, unchanged.

- **Market making / liquidity rewards** (`polymarket_lp_tool`): needs resting
  orders and live signing; revisit after live execution.
- **LLM news analyst** (TradingAgents, AutoPilotPM): costs per call and no
  measured edge; the momentum lane's metrics must first show attention matters.
- **Two-legged cross-venue arbitrage** (buy on one venue, sell on the
  other): needs a Kalshi account and order signing; the `fed` and
  `crossvenue` lanes use Kalshi as a reference price only.
