# Architecture decisions

The decisions that shape trading-polymarket, and why. Each was already stated,
with its reason, in the documents named under **Source**; this page,
started on 2026-10-31, collects them as `ADR-NNN` and adds no new ones. A new
decision gets the next number; a reversed one is marked **Superseded** and
points to the record that replaced it, never deleted.

| ADR | Decision | Status | Since |
|---|---|---|---|
| [ADR-001](#adr-001-a-module-not-an-engine) | A module, not an engine | Accepted | 0.1.0 |
| [ADR-002](#adr-002-free-keyless-data-only) | Free, keyless data only | Accepted | 0.1.0 |
| [ADR-003](#adr-003-paper-fills-walk-a-fresh-live-book) | Paper fills walk a fresh live book | Accepted | 0.1.0 |
| [ADR-004](#adr-004-paper-is-never-cheaper-than-live) | Paper is never cheaper than live | Accepted | 0.1.0 |
| [ADR-005](#adr-005-hold-to-resolution) | Hold to resolution | Accepted | 0.1.0 |
| [ADR-006](#adr-006-no-secrets-and-no-environment-variables-until-live) | No secrets and no environment variables until live | Accepted | 0.1.0 |
| [ADR-007](#adr-007-live-execution-only-after-a-stage-1-go) | Live execution only after a Stage 1 GO | Accepted | 0.1.0 |
| [ADR-008](#adr-008-research-writes-trading-core-audit-records) | Research writes trading-core audit records | Accepted | 0.1.0 |
| [ADR-009](#adr-009-one-http-client-with-an-injectable-transport) | One HTTP client with an injectable transport | Accepted | 0.1.0 |
| [ADR-010](#adr-010-kalshi-is-read-never-traded) | Kalshi is read, never traded | Accepted | 0.2.0 |
| [ADR-011](#adr-011-crossvenue-trades-reviewed-pairs-only) | `crossvenue` trades reviewed pairs only | Accepted | 0.2.0 |
| [ADR-012](#adr-012-each-lane-judged-alone-the-fed-lane-in-its-own-process) | Each lane judged alone; the fed lane in its own process | Accepted | 0.2.0 |
| [ADR-013](#adr-013-counted-runs-use-tagged-release-copies) | Counted runs use tagged release copies | Accepted | 0.2.0 |
| [ADR-014](#adr-014-runs-in-the-foreground-without-a-service-manager) | Runs in the foreground, without a service manager | Accepted | 0.2.1 |

## ADR-001: A module, not an engine

- **Decision:** trading-polymarket only implements trading-core's
  `TradingModule` and its lanes. Risk, the breaker, positions, accounting,
  the audit trail and the dashboard belong to trading-core. If the contract
  cannot express something, trading-core changes (with a default and docs).
- **Why:** one engine serves every venue; a workaround here would split the
  money logic in two places.
- **Consequences:** the module's only door into the engine is the contract
  ([`../ARCHITECTURE.md`](../ARCHITECTURE.md)); engine bugs are `TC-<n>` in
  trading-core.
- **Source:** `AGENTS.md` Local Norms, "A Module, Not An Engine";
  `docs/ARCHITECTURE.md` introduction.

## ADR-002: Free, keyless data only

- **Decision:** every data source is free and needs no account or key. A
  paid or keyed source is an optional extra with its own setting and its own
  evidence.
- **Why:** costs must be earned first; no lane has shown that it needs a paid
  source (X/Twitter's API is paid, so Google News RSS is the attention proxy).
- **Consequences:** Open-Meteo's free allowance is per IP, so forecasts are
  cached per station and research runs on the operator's own machine; the
  project pays nothing ([`COSTS.md`](COSTS.md)).
- **Source:** `docs/DATA-SOURCES.md` introduction and "Attention";
  [`RELEASE-GATE.md` §3.6](RELEASE-GATE.md#36-features-that-stay-off-until-proven);
  `AGENTS.md` "Free Data Only".

## ADR-003: Paper fills walk a fresh live book

- **Decision:** a paper buy or sell reads the CLOB book with `max_age=0` and
  walks it within the limit; a missing book, a closed market or an order
  below the market's minimum size refuses.
- **Why:** a paper fill must never succeed where a live one would not, or the
  paper stage proves nothing.
- **Consequences:** the paper executor's rules are the specification the live
  executor must match ([`../LIVE-TRADING.md`](../LIVE-TRADING.md)); what
  paper cannot model (queue position, latency, the book's reaction) is left
  to the live canary.
- **Source:** `docs/ARCHITECTURE.md` "Fill model (paper)"; `AGENTS.md`
  "No Read, No Fill".

## ADR-004: Paper is never cheaper than live

- **Decision:** fees come from each market's `feeSchedule`; a fee-enabled
  market without one is priced at `unknown_fee_rate` (0.07, the highest known
  category rate). A fee is never defaulted to zero.
- **Why:** an underpriced fee would make paper look better than live.
- **Source:** `docs/DATA-SOURCES.md` "Fees"; `AGENTS.md` "Paper Is Never
  Cheaper Than Live".

## ADR-005: Hold to resolution

- **Decision:** positions are held to resolution and redeemed at 1 or 0 with
  no fee. The example configs set the engine's `exits: {}`,
  `close_positions_on_shutdown: false` and `risk.max_loss_per_trade: 0`.
  Only the reference lanes sell early, on convergence, and `exit_at_bid`
  stays off until proven.
- **Why:** selling a 0.98 winner into the bids pays the spread and the taker
  fee for nothing; a binary position's mark can swing from 0.4 to 0.05 and
  back within a day, so a per-trade loss cap would sell at the worst moment.
- **Source:** `docs/CONFIGURATION.md` introduction; `docs/STRATEGY.md` §1;
  `AGENTS.md` "Hold To Resolution".

## ADR-006: No secrets and no environment variables until live

- **Decision:** the module reads no environment variable and holds no key.
  When live execution is built, its credentials come from `TRADING_PM_*`
  environment variables only, never from settings files.
- **Why:** every source is keyless, so nothing needs a secret. When one is
  needed, trading-core's rule applies: secrets never enter settings files,
  and a module reads its own credentials from its own environment variables
  (trading-core `AGENTS.md`, "Safety").
- **Source:** `docs/CONFIGURATION.md` "Files the module reads" (before
  2026-10-31: "There are no environment variables and no secrets");
  `docs/LIVE-TRADING.md` "What it needs" (Keys); [`../ENVIRONMENT.md`](../ENVIRONMENT.md).

## ADR-007: Live execution only after a Stage 1 GO

- **Decision:** live execution is deliberately not built until a lane has a
  Stage 1 GO, and is then gated like a release. Until then `LiveExecutor`
  refuses every order and the balance read, so the engine keeps entries
  blocked.
- **Why:** evidence before money: a lane moves towards real money only on a
  pre-registered GO, and live trading is the stage after paper.
- **Consequences:** with `"mode": "live"` and `--live` the module refuses,
  so no configuration can trade real money by mistake, and nothing in the
  repository holds or needs a key.
- **Source:** `docs/LIVE-TRADING.md`; `README.md`; `AGENTS.md` "Evidence
  Before Money".

## ADR-008: Research writes trading-core audit records

- **Decision:** every backtest writes trading-core audit records
  (`mode: backtest`).
- **Why:** the same audit tools and the same pre-registered rules then judge
  backtests, paper runs and live runs.
- **Source:** `docs/ARCHITECTURE.md` "Design rules"; `docs/RESEARCH.md` §3.

## ADR-009: One HTTP client with an injectable transport

- **Decision:** every request goes through one client (`clients/http.py`):
  a `User-Agent`, pacing per host, retries with backoff, counters on the
  dashboard; its transport is injectable.
- **Why:** Cloudflare answers 403 without a `User-Agent`; one client gives
  one place for pacing and counters; an injectable transport lets the tests
  run without the network.
- **Source:** `docs/DATA-SOURCES.md` introduction; `docs/ARCHITECTURE.md`
  "Design rules"; `docs/dev/TESTING.md`.

## ADR-010: Kalshi is read, never traded

- **Decision:** the `fed` and `crossvenue` lanes use Kalshi's free quote as a
  reference price only; there is no hedge leg and no Kalshi order.
- **Why:** a second leg needs a Kalshi account and order signing; the
  reference alone is free and keyless.
- **Consequences:** the edge can only be the venues' temporary disagreement,
  harvested by convergence exits; two-legged arbitrage is a proposed
  feature ([`PROPOSED-FEATURES.md`](PROPOSED-FEATURES.md)).
- **Source:** `docs/STRATEGY.md` §5; `docs/DATA-SOURCES.md` "Kalshi";
  `docs/dev/PROPOSED-FEATURES.md`.

## ADR-011: `crossvenue` trades reviewed pairs only

- **Decision:** the `crossvenue` lane trades only pairs in a file a human
  wrote with `pairs approve` after reading both venues' rules;
  `pairs suggest` only proposes.
- **Why:** look-alike markets are not the same bet when the settlement
  source, cut-off time or tie rule differ; the first `suggest` paired a 2028
  nomination with the Iowa caucus, and Polymarket listed a thin duplicate
  Fed event that resolved differently from the real one.
- **Source:** `docs/STRATEGY.md` §5; `AGENTS.md` Learnings Log "[PAIRS] Same
  Title, Different Bet".

## ADR-012: Each lane judged alone; the fed lane in its own process

- **Decision:** every lane has its own settings, its own `strategy` tag and
  its own pre-registered verdict file. The `fed` lane runs in its own
  trading-core process.
- **Why:** a lane moves up only on its own evidence; a separate process keeps
  the fed lane's breaker, exposure and audit trail from mixing with the
  weather lane's.
- **Source:** `docs/ARCHITECTURE.md` "Design rules"; `docs/dev/RUNBOOK.md`
  §3.3 (before 2026-10-31 `docs/PAPER-TRADING.md`).

## ADR-013: Counted runs use tagged release copies

- **Decision:** counted runs never run from the working repositories but
  from tagged copies in runtime-trading, each release in its own venv.
- **Why:** the repositories can change while a run keeps the code it was
  registered with; the install script refuses a dirty or moved copy, and
  each run's `run_started` records both commits.
- **Source:** `docs/dev/releases/0.2.0.md` "Code"; `docs/dev/releases/0.2.1.md`
  "Code"; [`RUNBOOK.md` §1](RUNBOOK.md#1-the-runtime-folder).

## ADR-014: Runs in the foreground, without a service manager

- **Decision:** runs start in a terminal (or tmux), with no service manager
  and no automatic restart; cron only for `metars`.
- **Why:** the dashboard shows failures as they happen, and a stopped run is
  a stopped terminal, which a background service hides. After a crash the
  operator reads why before restarting.
- **Source:** `CHANGELOG.md` 0.2.1 "Changed"; [`RUNBOOK.md` §3.2](RUNBOOK.md#32-run).
