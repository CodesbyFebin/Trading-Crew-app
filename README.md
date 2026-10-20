# Grok Trading Crew — paper-only build

> **WARNING: Trading can lose all of your capital. This software claims no profitability and assumes no edge.
> It runs in PAPER/REPLAY only. No live orders, no exchange keys. The only optional network use is the advisory LLM gateway (off unless you add a key). Not financial advice.**

## Run
```
scripts/run_all.sh          # installs deps, runs pytest, drills, a paper run, then serves http://127.0.0.1:8795
```
Tokens (`CREW_OWNER_TOKEN`, `CREW_OPERATOR_TOKEN`, `CREW_VIEWER_TOKEN`) and the approval HMAC key (`CREW_APPROVAL_HMAC_KEY`)
come from env only; if unset, run_all.sh generates throwaway ones and prints login URLs. `LIVE_ENABLED=false` is forced.

Other entry points: `scripts/run_drills.py` (writes `reports/drills-*.json|md`), `scripts/run_paper_day.py`
(writes `reports/paper-day-*.json|md` honest report + an append-only SQLite ledger).

## Layout
- `crew/models.py` Event, Ticket state machine (legal transitions enforced), TraceRow, RiskEvent, HMAC Approval, versioned ConfigStore
- `crew/bus.py` Bus interface + in-process asyncio bus (leases, idempotency, DLQ, backpressure, stale drop); RedisStreamsBus (real, optional via REDIS_URL-style client)
- `crew/store.py` SQLite append-only ledger/trace/risk/audit (UPDATE/DELETE blocked by triggers); PostgresStore (real, optional via DATABASE_URL), RLock write lock
- `crew/risk.py` deterministic Decimal risk engine, fail-closed, at-limit = breach; immutable file limits + LimitsAuditor
- `crew/modes.py` REPLAY→PAPER→LIVE_APPROVAL→LIVE_AUTO ladder, pure gate functions, auto-demotion
- `crew/killswitch.py`, `crew/drills.py` kill, drawdown, auto-demotion, limits-tamper, bus chaos drills
- `crew/agents.py` 50-agent registry (async workers, concurrency, SLA, health, metrics)
- `crew/overseer.py` Main Grok: routing, fan-out/fan-in with deadlines, quorum ≥2 lanes, arbiter rationale to trace, budgets, escalation
- `crew/desk_d4.py` + `crew/engine.py` D4 crypto paper pipeline on the Binance replay sample
- `crew/desks_synthetic.py` D1/D2/D3 on synthetic fixtures, REPLAY-locked
- `crew/desk_d5.py` D5 India NSE (archived, checks-only replay, SEBI gate checklist)
- `crew/connectors.py` connector interface, replay/fixture adapters, disabled live adapters
- `crew/api.py` FastAPI REST + WebSocket, RBAC; `web/` dashboard

## Deviations from blueprint
- **LLM roles restricted.** No LLM makes trade or risk decisions; no LLM is called at all in this build. News/social agents
  (S07, S08) and LLM synthesis agents (S18, S21, S22, S25) are registered but `DISABLED_BY_POLICY`. News can only block trades
  through a deterministic event calendar (owner rule).
- **LIVE-AUTO disabled.** Its gate always returns blocked: `owner policy: not enabled`. Any promotion beyond PAPER also needs a
  signed owner approval, and the API refuses any mode above PAPER. Live adapters exist but raise unconditionally.
- **Desk D3 memecoin and Desk D1 Polymarket are not approved by the owner.** They run on synthetic fixtures only, locked to REPLAY.
  D2 equities research likewise synthetic-fixture only.
- **Desk D5 India** is `ARCHIVED_RESEARCH_ONLY / NOT_APPROVED_BY_OWNER`. No strategy runs (all prior candidates were rejected; a
  restart needs a new strategy + explicit owner approval). It reuses `/workspace/indiatrader` read-only for Gate 0 limits,
  PIT universe, calendar and cost model. No production blackout calendar exists, so entries fail closed (CALENDAR_MISSING).
  SEBI gates (algo-ID, static IP, order-rate threshold, owner 2FA, audit trail, live enabled) all block leaving REPLAY.
  The 10 orders/sec threshold is an assumption to verify against current SEBI/NSE circulars and Fyers.
- **Agent names S24–S50 are inferred**; the pasted blueprint was truncated after S23. Marked with `*`.
- 2FA is represented by HMAC-signed owner approvals; there is no TOTP. Docker is not used (not available on the build box).
- D4 strategy is a simple EMA-cross + regime-quorum placeholder to exercise the pipeline. Its results are not evidence of an
  edge. Every variant tried is logged in the report.
- Fee model: 10 bps taker, assumed; verify against current Binance fees before any use.

## Brain layer (added 2026-10-20)
- `crew/memory.py`: **single shared memory**, append-only facts `(agent_id, topic, kind, content, provenance, ts)`. SQLite at
  `var/shared_memory.db` by default, or Postgres when `DATABASE_URL` is set in `.env` (free Neon/Supabase work). `GET /api/memory`, Memory page.
- `crew/skills.py`: 15 deterministic trading skills (indicators, sizing, Kelly cap, fee/slippage book walk, lot-step dust, Brier,
  reconciliation, D5 time window, SEBI order-rate check). `GET /api/skills`, `POST /api/skills/{name}`, Skills page.
- `crew/backtest.py`: S15 grid backtest (in-sample, synthetic sample, all variants shown). `GET /api/backtests`, owner-only `POST /api/backtests/run`.
- `crew/llm_router.py`: **advisory-only** OpenAI-compatible gateway. Fallback order OpenRouter (`:free` models) → Kilo gateway
  (`KILOCODE_BASE_URL` overridable) → Groq → Cline. Keys only from env/.env: `OPENROUTER_API_KEY`, `KILOCODE_API_KEY`, `GROQ_API_KEY`
  (+`GROQ_MODEL`), `CLINE_API_KEY` (+`CLINE_MODEL`). Without a key: `NOT CONFIGURED`. The model IDs in `config/llm_routing.json` were
  checked against the public model lists saved in `config/llm_sources.json`.
- `crew/jev.py` + the JEV page: an advisory chat that reads only whitelisted read-only tools and can save advisory notes to memory. It refuses
  orders, mode/limit changes, approvals and keys before any LLM call.
- `tests/test_brain.py::test_no_llm_path_reaches_order_risk_mode_code` checks with AST that no order/risk/mode module imports the router, JEV or memory reads.
- Full audit: `reports/AUDIT.md`.
