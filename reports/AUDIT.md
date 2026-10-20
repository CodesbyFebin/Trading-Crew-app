# Audit: mock, stub, synthetic, placeholder, hardcoded and simulated features
Date: 2026-10-20 (IST). Scope: every file in `crew/`, `web/`, `scripts/`, `config/`, `fixtures/`, `tests/conftest.py`.
Categories: **(a)** fixable offline now · **(b)** needs live data or keys, so blocked by owner policy · **(c)** intentional safety stub.
Status: FIXED = done in this commit; OPEN = still present (reason given).

| # | Where (file:line at audit time) | What is mock or fake | Cat | Status |
|---|---|---|---|---|
| 1 | crew/store.py:43 `PostgresStore` | raised NotImplementedError | a | FIXED: real psycopg 3 adapter, server-side append-only trigger, `make_store()` picks it from `DATABASE_URL`. Tested against a local Postgres 17 (2 tests, run only when `TEST_DATABASE_URL` is set) |
| 2 | crew/bus.py:77 `RedisStreamsBus` | raised NotImplementedError | a | FIXED: real redis-py Streams adapter (consumer groups, SET NX idempotency, XAUTOCLAIM lease timeout, DLQ stream, backpressure). Tested with fakeredis; **not tested against a real Redis server**. Not wired by default (InProcessBus remains the default) |
| 3 | crew/store.py:19 | no write lock ("serialized by GIL") | a | FIXED: RLock on all reads and writes, WAL for file DBs; 8-thread × 200-write test |
| 4 | API | no `/api/backtests` | a | FIXED: `crew/backtest.py` (S15) runs the full D4 pipeline over a fixed 6-variant grid; GET for viewers, POST re-run for owner only; all variants reported |
| 5 | (missing) | no shared memory | a | FIXED: `crew/memory.py`, a single append-only store (SQLite, or Postgres via `DATABASE_URL`); deterministic agents S09/S34/S44/S45/S47/S48 write facts each run; `/api/memory` + Memory page |
| 6 | (missing) | no skills catalog | a | FIXED: `crew/skills.py`, 15 deterministic tools; `/api/skills` + Skills page |
| 7 | (missing) | no LLM routing | a | FIXED (advisory only): `crew/llm_router.py`; NOT CONFIGURED without a key; never fabricates output |
| 8 | crew/engine.py:120 | `R[k].calls += 0` no-op that looked like agent activity | a | FIXED: removed |
| 9 | crew/engine.py:127 | `S47.calls += 1` manually bumped metric | a | FIXED: removed; S47 now shows its real call count (0) |
| 10 | crew/engine.py:69 | D4 quorum lane `"S10": lambda: "LONG"` always agrees, because entry is only evaluated on a cross-up. So the 2-lane quorum is effectively **one** independent lane (S14 regime) | a | OPEN: fixing it changes the Track 1 strategy, which the owner froze until the paper logs are approved. Disclosed here |
| 11 | crew/engine.py:99 | S43/S45 "run" lambdas that return values already computed inline, so the agents' call counts are cosmetic | a | OPEN: low risk; disclosed |
| 12 | crew/engine.py:132 | `strategy_variants_tried` is a hardcoded list describing an earlier manual run | a | OPEN: values match the run they describe; the Backtests page now records variants programmatically |
| 13 | crew/engine.py:134 | `llm_cost_usd: "0.00"` is hardcoded; true for the engine (0 tokens) but JEV/router calls are not metered into it | a | OPEN: router logs calls but not tokens or cost |
| 14 | crew/engine.py (ledger/trace reads) | reconciliation and win count read **all** rows. On a persistent shared Postgres with earlier runs, drift would be wrong | a | OPEN: SQLite default is per-run in-memory; needs a run_id column before Postgres is used for ledgers |
| 15 | crew/agents.py:40-66 | names and tasks for S24–S50 are inferred (asterisked). The owner's full blueprint (t73u) was not reconciled | a | OPEN: blueprint text not available in this workspace |
| 16 | fixtures/binance_replay_sample.jsonl; crew/desk_d4.py:1 | D4 prices are a **synthetic** replay sample, not market data | b | OPEN: real data means a live feed; Track 1 has no live/testnet integration until the owner approves the paper logs |
| 17 | fixtures/d1_*.json, d2_*.json, d3_*.json; crew/desks_synthetic.py | D1/D2/D3 run on synthetic fixtures | b | OPEN: desks NOT_APPROVED_BY_OWNER (Polymarket not approved for India) |
| 18 | crew/desk_d4.py:9 `FEE_RATE=0.001` | assumed 10 bps fee | b | OPEN: unverified assumption; needs the account fee tier |
| 19 | crew/desks_synthetic.py:34 `fee=0.02` | assumed prediction-market fee | b | OPEN: unverified |
| 20 | crew/desk_d4.py:75 `frac=0.015` sizing; crew/engine.py:21 `START_EQUITY=10000` | hardcoded paper parameters | c | intentional paper constants |
| 21 | crew/desks_synthetic.py:26 `seed=7` Monte Carlo | seeded simulation | c | intentional (reproducible) |
| 22 | crew/desk_d5.py:38 SEBI `10 orders/s` | assumed threshold | b | OPEN: verify against current SEBI/NSE circulars |
| 23 | crew/desk_d5.py:96 `calendar = None` | no versioned blackout calendar, so every entry is blocked | b | OPEN: needs a verified official calendar; intentionally fails closed |
| 24 | crew/desk_d5.py:45 OwnerSignals (algo-ID, static IP, 2FA via HMAC stand-in, audit flag) | all False | c | intentional: Gate 0 locked until owner signals |
| 25 | crew/connectors.py:53 `LiveAdapter` ×4 | always raise LiveDisabled | c | intentional safety stub |
| 26 | crew/agents.py S02,S04,S07,S08,S49 | disabled: need external feeds | b | OPEN |
| 27 | crew/agents.py S18,S21,S22,S25 | LLM roles disabled | c | intentional (owner rule). JEV is the only LLM consumer, advisory only |
| 28 | crew/agents.py S37–S41,S46 | live executors/wallet disabled | c | intentional |
| 29 | crew/modes.py LIVE_AUTO gate | always blocked | c | intentional |
| 30 | crew/bus.py:9 `RateLimited` | simulated 429 used by the chaos drill | c | intentional (drill) |
| 31 | crew/drills.py:44, tests/conftest.py:4 | fallback HMAC keys `drill-only-key`, `test-only-key` | c | test/drill only; the app needs env keys |
| 32 | scripts/run_all.sh:8 | generates throwaway tokens if env unset | c | intentional dev convenience; printed only to the local console |
| 33 | web/app.js Reactor dot, Floor room art, JEV pixel room | decorative animation | c | labelled "decorative" in the UI; all numbers are from the run |
| 34 | crew/connectors.py:13 `docs_verified=False` everywhere | no venue docs verified | b | OPEN |
| 35 | (requested) "Jev-Claw" connection | could not identify a product or API by that name | – | NOT DONE: not verifiable; the JEV assistant was built instead |

**Counts (35 items):** (a) 15: #1–15, of which 9 are FIXED and 6 OPEN · (b) 8: #16, 17, 18, 19, 22, 23, 26, 34, all OPEN and blocked by owner policy or unverified · (c) 11: #20, 21, 24, 25, 27–33, intentional · uncategorised 1: #35.
