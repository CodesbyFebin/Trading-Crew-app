# Trading Crew: a paper-only, multi-agent trading research platform

> **Read this first.** This software does **not** trade real money. It runs in **REPLAY and PAPER mode only**. It has no live
> exchange integration, holds no exchange keys and places no real orders. Every result in this README comes from
> **synthetic or replayed sample data** and is **not evidence of a profitable strategy**. Trading can lose all of your capital.
> Nothing here is financial advice, and the project makes **no profit claims of any kind**.

Trading Crew is an open-source Python/FastAPI application that models a "crew" of 50 small, typed, deterministic agents.
Together they take a market-data replay through data QA, feature engineering, regime detection, sizing, a hard-coded risk
engine, paper fills, settlement, reconciliation and honest reporting. A dashboard shows every step, and an append-only ledger
and trace record every decision.

The project is built with a **risk-officer mindset**. Capital preservation comes first, risk controls fail closed, and every
number on the dashboard is either a real output of the code running on the bundled sample data or clearly labelled as
decorative or synthetic. When something is missing, the app says so ("NOT CONFIGURED", "DISABLED_BY_POLICY",
"CALENDAR_MISSING"). It never fills the gap with plausible-looking fake data.

---

## Table of contents
1. [What this is (and is not)](#what-this-is-and-is-not)
2. [Safety architecture](#safety-architecture)
3. [Mode ladder](#mode-ladder)
4. [Desks](#desks)
5. [The 50 agents](#the-50-agents)
6. [Trading skills catalog](#trading-skills-catalog)
7. [Shared memory](#shared-memory)
8. [Model router (advisory only)](#model-router-advisory-only)
9. [JEV, the advisory assistant](#jev-the-advisory-assistant)
10. [Quickstart](#quickstart)
11. [Configuration and environment variables](#configuration-and-environment-variables)
12. [API reference](#api-reference)
13. [Testing and drills](#testing-and-drills)
14. [Reference results (synthetic data)](#reference-results-synthetic-data)
15. [Audit summary and known limitations](#audit-summary-and-known-limitations)
16. [Project layout](#project-layout)
17. [Contributing, security, license](#contributing-security-license)
18. [Disclaimers](#disclaimers)

---

## What this is (and is not)

**It is:**
- A reproducible **research and paper-trading harness**. Given the same input file it produces the same fills, the same fees
  and the same report, down to the last decimal. All money math uses Python `Decimal`, never floats.
- A **reference implementation of trading safety controls**: a fail-closed risk engine, immutable file-based limits with
  tamper detection, a kill switch, a promotion ladder that requires signed owner approval, and an append-only audit trail
  enforced by database triggers.
- A **multi-agent pipeline** in which every "agent" is ordinary deterministic Python with metrics (calls, errors, average
  latency, SLA breaches, queue depth) that the dashboard shows live.
- A **dashboard** (FastAPI and vanilla JavaScript) with 17 pages: Command Center, Reactor, Floor, Crew Pool, Tickets & Trace,
  Markets, Research, India D5, Risk Console, Connectors, Approvals, Reports, Backtests, Memory, Skills, LLM Routing and JEV.

**It is not:**
- A trading bot you can point at an exchange. Live adapters exist only as stubs that raise before any network code could run.
- An AI that decides trades. **No large language model (LLM) ever makes a trade or risk decision.** The optional LLM gateway
  can only produce advisory text notes. A test proves that no LLM code path can reach the order, risk or mode modules.
- A profitable strategy. The sample strategy is a placeholder (an EMA crossover gated by a regime filter). On the bundled
  synthetic sample it **loses money after costs** (see [Reference results](#reference-results-synthetic-data)).

---

## Safety architecture

The safety design rests on one principle: **hard limits live in code and files outside any model, and every failure mode
blocks the trade instead of allowing it.**

### 1. Deterministic risk engine (`crew/risk.py`)
Every order intent passes through `RiskEngine.check()` before a paper fill can happen.
- **Fail closed.** The check runs with a timeout. If it times out, raises an exception or returns the wrong type, the order
  is vetoed with a reason that starts with `fail-closed:`.
- **At-limit counts as a breach.** Comparisons use `>=`, so an exposure exactly equal to a cap is rejected.
- **Decimal only.** Non-Decimal numeric inputs are rejected, which caught a real bug during development (an empty `sum()`
  returned an `int`).
- **Limits come from `config/limits.json`** and are loaded read-only, together with their SHA-256 hash. A `LimitsAuditor`
  re-hashes the file and logs `LIMITS_FILE_CHANGED` as a critical risk event when the file is modified. The API refuses any
  attempt to change limits at runtime and writes that attempt to the audit log.

The limits currently in `config/limits.json`:

| Limit | Value |
|---|---|
| max position (fraction of equity) | 0.02 |
| max gross exposure | 0.20 |
| per-venue cap | 0.10 |
| daily loss | 0.02 |
| weekly loss | 0.05 |
| max slippage | 20 bps |
| min liquidity (24h quote volume) | 100,000 USD |
| max open positions | 3 |
| post-loss cooldown | 1,800 s |
| withdrawals | disabled (`false`) |
| drawdown halt | 0.10 |

### 2. Kill switch (`crew/killswitch.py`)
An operator or owner can engage the kill switch from the Risk Console or with `POST /api/kill`. It halts every desk, marks
open tickets and blocks any new order. Resetting it requires a signed owner approval.

### 3. Signed approvals (`crew/models.py`)
Owner approvals are HMAC-signed with a key read from the `CREW_APPROVAL_HMAC_KEY` environment variable. Without the key,
approvals cannot be signed. A signed approval is **necessary but not sufficient**: the promotion gates still apply.

### 4. Append-only storage (`crew/store.py`, `crew/memory.py`)
The trace, ledger, risk events, audit log and shared memory are append-only. In SQLite, `BEFORE UPDATE` and `BEFORE DELETE`
triggers raise an error. In Postgres, a PL/pgSQL trigger function does the same. All writes go through a process-wide lock.

### 5. Authentication and roles (`crew/auth.py`, `crew/api.py`)
- Three roles: **owner** (view, approve, kill, mode change, config), **operator** (view, kill) and **viewer** (view).
- Tokens come from environment variables only and are accepted **only** in the `Authorization: Bearer` header. Tokens in the
  URL are rejected, and the UI removes them from the address bar.
- The WebSocket authenticates with a first message `{"auth": "<token>"}` sent within 5 seconds.
- Optional **TOTP** (time-based one-time password) for owner actions: set `CREW_OWNER_TOTP_SECRET` and send an `X-TOTP`
  header. It is disabled when the variable is unset.

### 6. LLM isolation
`tests/test_brain.py::test_no_llm_path_reaches_order_risk_mode_code` parses the source of every decision module (risk, modes,
kill switch, engine, connectors, desks, overseer, models, bus, store, agents, drills, skills, backtest) and fails if any of
them imports the LLM router, JEV or memory-read functions. The engine only *writes* deterministic facts to memory; it never
reads them back.

### 7. Secrets policy
- No keys in code, chat or command-line arguments.
- Secrets live only in `.env`, which is gitignored; `.env.example` lists the variables with empty values.
- The application needs **no exchange keys at all**, and no key may ever have withdrawal permission.

---

## Mode ladder

`REPLAY → PAPER → LIVE_APPROVAL → LIVE_AUTO` (`crew/modes.py`)

- Promotion moves **one rung at a time**, and each step has a pure gate function over recorded statistics
  (out-of-sample net expectancy, calibration, number of paper days, reconciliation drift, kill-drill result, slippage within
  model).
- Any promotion beyond PAPER also needs a valid **signed owner approval**.
- The API **cannot set any mode above PAPER** in this build.
- **LIVE_AUTO is unreachable.** Its gate always returns `owner policy: not enabled`.
- `LIVE_ENABLED=false` is the default and is forced by the run scripts and the Docker image.
- Any breach **auto-demotes one rung**. The auto-demotion drill shows LIVE_APPROVAL → PAPER → REPLAY.

---

## Desks

| Desk | What | Data | Status |
|---|---|---|---|
| D4 | Crypto signals (Binance-style spot) | `fixtures/binance_replay_sample.jsonl`: **synthetic** sample prices, 8,640 one-minute snapshots over about 3 days, BTCUSDT and ETHUSDT | PAPER (paper only; no live or testnet integration until the owner approves the paper logs) |
| D1 | Prediction markets (Polymarket-style) | synthetic fixture | NOT_APPROVED_BY_OWNER, locked to REPLAY |
| D2 | Equities night research (filings) | synthetic fixture | NOT_APPROVED_BY_OWNER, locked to REPLAY |
| D3 | Memecoin scanner (rug filters) | synthetic fixture | NOT_APPROVED_BY_OWNER, locked to REPLAY |
| D5 | India NSE equities (SEBI) | local NSE bhavcopy files from a separate archived project (optional) | ARCHIVED_RESEARCH_ONLY / NOT_APPROVED_BY_OWNER, checks-only replay |

**D5 India** runs **no strategy**. Its replay exercises only the risk, universe, timing and calendar checks, using labelled
probe intents. Its locked "Gate 0" terms are:
- CNC (delivery) only and long-only; MIS, MTF, NRML, BO and CO products are rejected.
- Risk limits: 1% risk per trade; a 10% per-stock cap (exactly 10% counts as a breach); 2% daily, 3% weekly and 6% drawdown
  limits.
- Times (IST): entries stop at 15:00, square-off at 15:20, disable at 15:25.
- Blackout dates come from a versioned calendar. **No verified calendar exists**, so every entry is blocked
  (`CALENDAR_MISSING`).

A SEBI/go-live checklist blocks D5 from ever leaving REPLAY. It requires:
- a new approved strategy;
- broker algo-ID confirmation;
- a whitelisted static IP;
- an order rate below 80% of an **assumed** 10 orders per second threshold (to be verified against current circulars);
- signed owner 2FA;
- a verified audit trail;
- `LIVE_ENABLED`, which is always false here.

When the archived project is absent (for example on a fresh clone or in CI), the D5 replay tests skip cleanly.

---

## The 50 agents

Each agent is an `Agent` object (`crew/agents.py`) with its own concurrency semaphore, SLA timeout and metrics. Agents run
plain Python functions. A state other than `ENABLED` means the agent refuses to run.
- **DISABLED_BY_POLICY:** it needs a live feed, live execution or an LLM decision role, all of which are forbidden.
- **NOT_APPROVED_BY_OWNER:** the owner has not approved that venue.
- **DISABLED_IDLE:** no real work exists for it on the available data.

Names after S23 are marked `*`. They were inferred because the pasted blueprint was cut off, and they have not yet been
reconciled with the full blueprint.

The call counts below come from **one reference paper day** on the bundled sample, generated by running the engine.
In that run, 32 of the 34 enabled agents were invoked:
- S34 (VetoClerk) runs only when the risk engine vetoes a trade, and there were 0 vetoes in this run.
- S15 (Backtester) runs on `/api/backtests/run` and `scripts/run_backtests.py`.

Two disclosed caveats:
- **S10 and S14 quorum.** In D4 the quorum is "S10 and S14 agree on LONG". S10 computes its verdict from the EMA features,
  but it is evaluated only on an EMA cross-up, so it always agrees. The quorum is therefore effectively one independent
  check (S14). This is disclosed rather than "fixed", because changing it would alter the frozen Track 1 strategy.
- **Post-run monitors.** S11, S17, S29, S30, S31, S32, S33, S42 and S44 measure and record after the run. They are **not** in
  the trade decision path; the risk engine alone enforces the limits.

| ID | Name | Crew | Task | Status | Calls in reference paper day | Reason if not enabled |
|---|---|---|---|---|---|---|
| S01 | TapeWatcher | C1 | Trade/book stream (replay fixture) | ENABLED | 1 |  |
| S02 | OracleSync | C1 | Pyth/Chainlink staleness checks | DISABLED_BY_POLICY | 0 | needs external data feed; no network in this build |
| S03 | PredictionBook | C1 | Prediction-market catalog (synthetic fixture) | ENABLED | 1 |  |
| S04 | ChainStream | C1 | Solana/EVM mints and transfers | DISABLED_BY_POLICY | 0 | needs external data feed; no network in this build |
| S05 | DexScanner | C1 | DEX pairs (synthetic fixture) | ENABLED | 1 |  |
| S06 | FilingsFeed | C1 | SEC filings (synthetic fixture) | ENABLED | 1 |  |
| S07 | NewsWire | C1 | News / economic calendar | DISABLED_BY_POLICY | 0 | news/social only via deterministic event calendar per owner rule; feed not connected |
| S08 | SocialPulse | C1 | X/Telegram/Reddit velocity | DISABLED_BY_POLICY | 0 | news/social only via deterministic event calendar per owner rule; feed not connected |
| S09 | DataQA | C1 | Dedupe, schema, gaps, clock skew | ENABLED | 1 |  |
| S10 | FeatureForge | C2 | Deterministic features | ENABLED | 87 |  |
| S11 | VolModeler | C2 | Realized vol | ENABLED | 2 |  |
| S12 | MonteCarlo | C2 | Seeded path draws for P(up) | ENABLED | 3 |  |
| S13 | FairValue | C2 | Binary fair value, edge after fees | ENABLED | 3 |  |
| S14 | RegimeDetector | C2 | Trend/chop regime tags | ENABLED | 86 |  |
| S15 | Backtester | C2 | Replay engine | ENABLED | 0 |  |
| S16 | Calibrator | C2 | Brier score | DISABLED_IDLE | 0 | no resolved outcomes exist in the D1 fixture, so there is nothing real to calibrate |
| S17 | ModelRegistry | C2 | Versioned model params | ENABLED | 1 |  |
| S18 | EarningsReader | C3 | Transcript tone | DISABLED_BY_POLICY | 0 | LLM role; owner rule: LLMs never make trade/risk decisions and no LLM calls in this build |
| S19 | InsiderAnalyst | C3 | Form 4 cluster rules (synthetic fixture) | ENABLED | 3 |  |
| S20 | FilingsAnalyst | C3 | 8-K red-flag rules (synthetic fixture) | ENABLED | 3 |  |
| S21 | SectorAnalyst | C3 | Regulation mapping | DISABLED_BY_POLICY | 0 | LLM role; owner rule: LLMs never make trade/risk decisions and no LLM calls in this build |
| S22 | SentimentScorer | C3 | Sentiment scores | DISABLED_BY_POLICY | 0 | LLM role; owner rule: LLMs never make trade/risk decisions and no LLM calls in this build |
| S23 | TokenForensics | C3 | Deployer/rug rules (synthetic fixture) | ENABLED | 3 |  |
| S24 | HolderAnalyst* | C3 | Holder concentration rules (synthetic) | ENABLED | 3 |  |
| S25 | ThesisWriter* | C3 | Narrative synthesis | DISABLED_BY_POLICY | 0 | LLM role; owner rule: LLMs never make trade/risk decisions and no LLM calls in this build |
| S26 | MorningBrief* | C3 | Deterministic brief from report data | ENABLED | 1 |  |
| S27 | Sizer* | C4 | Fixed-fraction sizing (Decimal) | ENABLED | 12 |  |
| S28 | KellyCapper* | C4 | Fractional Kelly cap | ENABLED | 3 |  |
| S29 | ExposureMonitor* | C4 | Gross/venue exposure | ENABLED | 1 |  |
| S30 | LossGuard* | C4 | Daily/weekly loss tracking | ENABLED | 1 |  |
| S31 | LiquidityGate* | C4 | Min liquidity check | ENABLED | 1 |  |
| S32 | CorrelationGuard* | C4 | Correlated exposure | ENABLED | 1 |  |
| S33 | LimitsAuditor* | C4 | Limits hash audit | ENABLED | 1 |  |
| S34 | VetoClerk* | C4 | Records vetoes to trace | ENABLED | 0 |  |
| S35 | OrderRouter* | C5 | Routes to paper filler | ENABLED | 12 |  |
| S36 | PaperFiller* | C5 | Book-walk fills with fees+slippage | ENABLED | 24 |  |
| S37 | BinanceLiveExec* | C5 | Live Binance orders | DISABLED_BY_POLICY | 0 | live venue/wallet executor; LIVE_ENABLED=false and live gates cannot pass in this build |
| S38 | PolymarketExec* | C5 | Live Polymarket orders | NOT_APPROVED_BY_OWNER | 0 | live venue/wallet executor; LIVE_ENABLED=false and live gates cannot pass in this build |
| S39 | BrokerExec* | C5 | Alpaca/IBKR orders | DISABLED_BY_POLICY | 0 | live venue/wallet executor; LIVE_ENABLED=false and live gates cannot pass in this build |
| S40 | SolanaExec* | C5 | Solana swaps | NOT_APPROVED_BY_OWNER | 0 | live venue/wallet executor; LIVE_ENABLED=false and live gates cannot pass in this build |
| S41 | EVMExec* | C5 | EVM swaps | DISABLED_BY_POLICY | 0 | live venue/wallet executor; LIVE_ENABLED=false and live gates cannot pass in this build |
| S42 | SlippageMonitor* | C5 | Realized vs modeled slippage | ENABLED | 1 |  |
| S43 | Settler* | C6 | Position settlement | ENABLED | 1 |  |
| S44 | PnLAccountant* | C6 | Net-of-cost PnL | ENABLED | 13 |  |
| S45 | Reconciler* | C6 | Ledger vs positions | ENABLED | 1 |  |
| S46 | WalletWatcher* | C6 | Wallet balances | DISABLED_BY_POLICY | 0 | live venue/wallet executor; LIVE_ENABLED=false and live gates cannot pass in this build |
| S47 | HonestReporter* | C6 | Generated honest report | ENABLED | 1 |  |
| S48 | CostMeter* | C6 | Metered compute/LLM cost | ENABLED | 1 |  |
| S49 | Notifier* | C6 | Telegram/Slack/email alerts | DISABLED_BY_POLICY | 0 | needs external data feed; no network in this build |
| S50 | Archivist* | C6 | Audit log export | ENABLED | 1 |  |


---

## Trading skills catalog

`crew/skills.py` provides 15 deterministic, pure-Python tools. They do no I/O, make no network calls, use no LLM and work in
Decimal throughout. Agents and API users call them; they never place orders or change risk state. They are listed on the
**Skills** page and can be run with `POST /api/skills/{name}`.

| Skill | Category | What it does |
|---|---|---|
| `sma`, `ema` | indicator | moving averages |
| `rsi` | indicator | Wilder RSI |
| `atr` | indicator | average true range |
| `realized_vol` | risk metric | sample standard deviation of returns |
| `max_drawdown` | risk metric | peak-to-trough fraction |
| `position_size` | sizing | fixed-fractional risk sizing rounded down to the lot step; returns 0 on invalid input (fail closed) |
| `kelly_fraction` | sizing | Kelly fraction, capped and never negative |
| `fee_slippage` | costs | walks the order book: average price, slippage versus best price, fee (the fee rate is an assumption to verify) |
| `round_to_step`, `dust_after_rounding` | exchange | lot-step rounding and the leftover dust |
| `brier` | calibration | Brier score |
| `reconcile` | accounting | ledger cash versus engine cash drift |
| `india_entry_window` | calendar | D5 IST entry and square-off window |
| `india_order_rate` | compliance | peak orders per second versus the **assumed** SEBI threshold |

---

## Shared memory

`crew/memory.py` is **one** shared, append-only memory for all agents. Each fact records `agent_id`, `topic`, `kind`
(observation, metric, report, advisory or decision_record), `content`, `provenance`, a UTC timestamp, an `advisory` flag and a
SHA-256 hash.
- **Storage:** SQLite by default (`var/shared_memory.db`). Set `DATABASE_URL` to a Postgres URL to use Postgres instead; free
  tiers such as Neon or Supabase work. UPDATE and DELETE are blocked by triggers in both backends.
- **Who writes:** after each paper day, the deterministic agents S09, S34, S44, S45, S47 and S48 write what they measured.
- **Advisory facts:** facts with `kind="advisory"` must also set `advisory=True`. They come only from the LLM path and are never
  read by order, risk or mode code.
- **Access:** `GET /api/memory` supports `q`, `topic`, `agent_id` and `limit`. The **Memory** page shows and searches the facts.

---

## Model router (advisory only)

`crew/llm_router.py` is an OpenAI-compatible `/chat/completions` client with a fallback order, timeouts and a per-agent model
mapping (`config/llm_routing.json`). **It is optional and off by default.**

- **Provider order:** OpenRouter (`:free` models) → Kilo AI Gateway → Groq → Cline.
- **Keys** come only from env or `.env`: `OPENROUTER_API_KEY`, `KILOCODE_API_KEY` (base URL overridable with
  `KILOCODE_BASE_URL`), `GROQ_API_KEY` with `GROQ_MODEL`, and `CLINE_API_KEY` with `CLINE_MODEL`.
- **Without any key** the router reports **NOT CONFIGURED** and raises. It never fabricates a response.
- **Model IDs** were not invented. On 2026-10-20 they were checked against the public model lists (OpenRouter
  `https://openrouter.ai/api/v1/models` and the Kilo gateway `/models`). The snapshot is saved in `config/llm_sources.json`,
  and a test asserts that every configured model ID appears in it.
- **Not verified:** Cline's base URL comes from its docs, but it needs a key and no free tier was found. The Groq base URL was
  not re-verified, and its model must be supplied by you.
- **Output** is an `AdvisoryNote`: text only, labelled advisory.

---

## JEV, the advisory assistant

**JEV** is a chat panel (the pink "GROKBOT + JEV" page) backed by the model router.
- **What it reads.** JEV reads app state only through a fixed whitelist of read-only tools: summary, risk, audit, reports,
  memory, skills, desks, india and backtests. Each tool returns a JSON copy.
- **What it writes.** It can save its answer to shared memory as an advisory note.
- **What it cannot do.** It holds no reference to the engine, risk engine, mode controller, kill switch, connectors,
  approvals or keys. Requests to place orders, change modes or limits, approve anything or reveal keys are **refused in code
  before any LLM call**.
- **With no key** it shows **NOT CONFIGURED** together with the real read-only context it gathered, and it never invents an
  answer.

---

## Quickstart

### Local (Python 3.13)
```bash
git clone https://github.com/CodesbyFebin/Trading-Crew-app
cd Trading-Crew-app
cp .env.example .env          # optional: fill in tokens; leave LLM keys empty if you don't want JEV answers
scripts/run_all.sh            # venv + pinned deps, pytest, drills, paper day, backtests, then serves 127.0.0.1:8795
```
If you did not set tokens, `run_all.sh` generates throwaway ones and writes them to `var/session.env` (mode 600, gitignored).
It does not print them. Open http://127.0.0.1:8795/ and paste a token into the sign-in form.

### Docker
```bash
cp .env.example .env    # set CREW_*_TOKEN, CREW_APPROVAL_HMAC_KEY and POSTGRES_PASSWORD
docker compose up --build
```
- The image is `python:3.13-slim`, runs as non-root uid 10001 and contains no secrets.
- Compose starts the app plus `postgres:17-alpine` and `redis:7-alpine`.
- Verified so far: the image builds, and the container serves the API on SQLite.
- **Not yet verified:** the app reaching Postgres inside Docker, and `docker compose` end-to-end (see
  [known limitations](#audit-summary-and-known-limitations)).
- Redis is provisioned, but the runtime engine does not use a bus yet (only the drills do).

---

## Configuration and environment variables

| Variable | Purpose | Default |
|---|---|---|
| `LIVE_ENABLED` | live trading switch (forced `false`) | `false` |
| `CREW_OWNER_TOKEN` / `CREW_OPERATOR_TOKEN` / `CREW_VIEWER_TOKEN` | API role tokens | none (required) |
| `CREW_APPROVAL_HMAC_KEY` | signs owner approvals | none (approvals cannot be signed) |
| `CREW_OWNER_TOTP_SECRET` | optional TOTP for owner actions | unset = disabled |
| `DATABASE_URL` | Postgres for ledger and shared memory | unset = SQLite |
| `DB_CONNECT_TIMEOUT_S` | Postgres connect timeout | 10 |
| `CREW_MEMORY_PATH` | SQLite path for shared memory | `var/shared_memory.db` |
| `OPENROUTER_API_KEY`, `KILOCODE_API_KEY`, `KILOCODE_BASE_URL`, `GROQ_API_KEY`, `GROQ_MODEL`, `CLINE_API_KEY`, `CLINE_MODEL` | advisory LLM gateway | unset = NOT CONFIGURED |
| `INDIATRADER_ROOT` | path to the archived India project (D5 replay) | `/workspace/indiatrader` |
| `TEST_DATABASE_URL` | enables the Postgres tests | unset = skipped |

Files:
- `config/limits.json`: hard risk limits (immutable at runtime).
- `config/llm_routing.json`: providers, fallback order and agent-to-model mapping.
- `config/llm_sources.json`: the verified model-list snapshot.

---

## API reference

Every endpoint requires `Authorization: Bearer <token>`. Owner actions additionally need `X-TOTP` when TOTP is enabled.
JSON Schemas for all request bodies and typed models are in [`schemas/`](schemas/) (draft 2020-12).

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/api/whoami` | view | your role |
| GET | `/api/summary` | view | header stats (mode, paper PnL, fees, fills, kill state, LLM cost) |
| GET | `/api/agents` | view | the 50 agents with live metrics |
| GET | `/api/desks`, `/api/india` | view | desk status; D5 Gate 0, SEBI checklist and replay |
| GET | `/api/tickets`, `/api/trace` | view | ticket state machine history; append-only trace |
| GET | `/api/pnl`, `/api/markets`, `/api/research` | view | paper PnL and equity curve; fills and QA; D1–D3 fixture output |
| GET | `/api/reports`, `/api/reports/{name}` | view | generated reports |
| GET | `/api/risk`, `/api/drills` | view | limits, hash, kill state, risk events, drills |
| POST | `/api/drills/run` | operator | re-run the safety drills |
| GET/POST | `/api/connectors`, `/api/connectors/{name}/test` | view | connector health and contract tests |
| GET/POST | `/api/configs`, `/api/configs/rollback/{ver}` | owner | versioned config (risk limits are rejected) |
| GET/POST | `/api/mode` | owner | mode ladder (API capped at PAPER) |
| POST | `/api/kill` | operator | engage the kill switch |
| GET/POST | `/api/approvals` | owner | signed approvals |
| GET | `/api/audit` | view | audit log |
| GET / POST | `/api/backtests`, `/api/backtests/run` | view / owner | S15 grid backtests |
| GET | `/api/memory` | view | shared memory |
| GET / POST | `/api/skills`, `/api/skills/{name}` | view | skills catalog and execution |
| GET | `/api/llm` | view | router status and recent calls |
| POST | `/api/jev` | view | ask JEV (advisory) |
| WS | `/ws/{summary,agents,trace}` | view | live updates; first message `{"auth": token}` |

---

## Testing and drills

```bash
.venv/bin/pytest -q tests                                       # unit, integration and API tests
TEST_DATABASE_URL=postgresql://... .venv/bin/pytest -q tests    # also runs the Postgres tests
/workspace/.pwvenv/bin/python -m pytest tests_e2e               # Playwright smoke test of all 17 pages (needs playwright)
.venv/bin/python scripts/run_drills.py                          # safety drills; exits non-zero on failure
```

What the test suite covers:
- the ticket state machine;
- risk at-limit breaches and fail-closed behaviour;
- limits tampering;
- signed approvals;
- the mode gates;
- the bus (leases, idempotency, dead-letter queue, backpressure);
- the append-only triggers;
- paper reconciliation;
- RBAC, header-only auth, WebSocket first-message auth and TOTP;
- shared memory, the router (no key, and fallback), JEV refusals and LLM isolation;
- the skills;
- agent wiring;
- the JSON Schemas.

CI (`.github/workflows/ci.yml`) runs pytest against a Postgres service, then the drills and a paper day.

**Drills** (`crew/drills.py`), all PASS in the latest run:
1. **kill_switch**: halts every desk and blocks new orders.
2. **drawdown_halt**: passes at 5% drawdown, blocks at 10%, and the block persists.
3. **auto_demotion**: LIVE_APPROVAL → PAPER → REPLAY.
4. **limits_tamper**: a modified limits file is detected.
5. **bus_chaos**: duplicates, a simulated 429, lease timeouts, the dead-letter queue and backpressure are all handled.

---

## Reference results (synthetic data)

> These numbers come from the bundled **synthetic** replay sample. They demonstrate that the accounting is correct. They do
> **not** show an edge, and the sample is far too small to infer one.

**D4 paper day** (`reports/examples/paper-day-example.md`, regenerated by `scripts/run_paper_day.py`):

| Metric | Value |
|---|---|
| Input rows / kept after QA | 8,640 / 8,640 (0 duplicates, crossed, gaps or out-of-order rows) |
| Span | 2.999 days |
| Start → final equity (marked to bid) | 10,000 → 9,996.3482 USDT |
| **Net PnL after fees and slippage** | **−3.6518 USDT** |
| Fees paid | 3.5936 USDT (assumed 10 bps fee rate, unverified) |
| Average slippage | 0.50 bps |
| Fills / round trips / winners | 24 / 12 / 2 |
| Tickets settled / rejected (no quorum) / vetoed | 12 / 74 / 0 |
| Reconciliation drift | 0 |
| LLM tokens / LLM cost in the engine | 0 / $0.00 |

**Backtest grid** (S15, in-sample, every variant tried is shown, `reports/examples/backtests-example.json`):

| EMA fast/slow | Regime slope | Net PnL after costs (USDT) | Fills |
|---|---|---|---|
| 20/60 | 0.0001 | −3.6518 | 24 |
| 20/60 | 0.0005 | 0.0000 | 0 |
| 10/30 | 0.0001 | −10.9396 | 60 |
| 10/30 | 0.0005 | −5.7180 | 32 |
| 30/90 | 0.0001 | −1.9840 | 8 |
| 50/200 | 0.0001 | −0.5241 | 22 |

Every variant that traded lost money after costs. Picking the "least bad" one would be overfitting.

---

## Audit summary and known limitations

The full audit, with file and line references, is in [`reports/AUDIT.md`](reports/AUDIT.md). It lists 35 items:
- **15 fixable offline:** 9 fixed in the first round, with more fixed in the review round.
- **8 blocked by owner policy or by needing real data or keys.**
- **11 intentional safety stubs.**
- **1 uncategorised:** "Jev-Claw", which could not be identified.

Known limitations, stated plainly:
- **Data.** All market data is synthetic or replayed. There is no live or testnet connection, by owner policy, until the
  paper logs are reviewed and approved.
- **Unverified assumptions.**
  - the 10 bps Binance fee rate;
  - the 2% prediction-market fee;
  - the SEBI threshold of 10 orders per second;
  - no connector's venue documentation has been verified.
- **India D5.** No verified blackout calendar exists, so every entry is blocked.
- **Quorum.** The D4 quorum is effectively one independent lane (see the S10 note above).
- **Postgres reconciliation.** Reconciliation and the win count read all ledger and trace rows. On a shared, persistent
  Postgres that holds earlier runs, they would be wrong. A run id is needed before Postgres is used for the ledger.
- **Redis.** The Redis adapter has been tested only against fakeredis, and the runtime engine does not use it.
- **Docker.** `docker compose` and app-to-Postgres networking inside Docker are not yet verified.
- **LLM cost.** The LLM cost meter does not include JEV or router token usage.
- **Agent names.** S24–S50 have inferred names.

---

## Project layout
```
crew/        engine, agents, overseer, risk, modes, kill switch, store, memory, bus, connectors, desks, skills,
             backtest, llm_router, jev, api
web/         dashboard (index.html, app.js, css, icons)
config/      limits.json, llm_routing.json, llm_sources.json
fixtures/    synthetic replay sample and D1–D3 fixtures
schemas/     JSON Schemas (draft 2020-12), generated by scripts/gen_schemas.py
scripts/     run_all.sh, run_drills.py, run_paper_day.py, run_backtests.py, screenshots.py, gen_schemas.py
tests/       pytest suite; tests_e2e/ Playwright smoke tests
reports/     AUDIT.md and examples/ (runtime reports are gitignored)
docs/        MkDocs site (published to GitHub Pages)
```

---

## Contributing, security, license

- See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md). Changes that weaken a safety rule will not be accepted.
- Report vulnerabilities privately; see [SECURITY.md](SECURITY.md). **Never post keys or tokens in issues.**
- Code of conduct: [Contributor Covenant 2.1](CODE_OF_CONDUCT.md).
- License: [MIT](LICENSE), © 2026 CodesbyFebin.
- Sponsorship: `.github/FUNDING.yml` shows a Sponsor button. GitHub Sponsors must be enabled on the owner's account for it to work.

---

## Disclaimers

- **Paper only.** This software does not place real orders and contains no live trading integration.
- **Not financial advice.** Nothing in this repository is investment, legal or tax advice.
- **No profit claims.** No result here shows or implies future profitability. The reference results are negative after costs.
- **Synthetic data.** Every result comes from synthetic or replayed sample data.
- **Your responsibility.** If you modify this software to trade real money, you alone are responsible for compliance
  (including SEBI rules in India and the rules in your own jurisdiction) and for any losses. Trading can lose all of your capital.
