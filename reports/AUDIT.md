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
| 10 | crew/engine.py:69 | D4 quorum lane `"S10": lambda: "LONG"` always agrees, because entry is only evaluated on a cross-up. So the 2-lane quorum is effectively **one** independent lane (S14 regime) | a | PARTLY FIXED: S10 now computes its verdict from the EMA features instead of returning a constant, so the call is real. It is still **not independent**: within this branch it always agrees, so the quorum is effectively S14 alone. A truly independent lane would change the frozen Track 1 strategy |
| 11 | crew/engine.py:99 | S43/S45 "run" lambdas that return values already computed inline, so the agents' call counts are cosmetic | a | FIXED: S43 now marks open positions and S45 reads the ledger and computes drift inside their own runs |
| 12 | crew/engine.py:132 | `strategy_variants_tried` is a hardcoded list describing an earlier manual run | a | OPEN: values match the run they describe; the Backtests page now records variants programmatically |
| 13 | crew/engine.py:134 | `llm_cost_usd: "0.00"` is hardcoded | a | FIXED (round 3): engine cost is computed from its token count, and the router meters provider `usage` × verified price (else UNKNOWN); the API merges them |
| 14 | crew/engine.py (ledger/trace reads) | reconciliation and win count read **all** rows. On a persistent shared Postgres with earlier runs, drift would be wrong | a | FIXED (round 3): `run_id` on all store tables with composite keys and indexes, scoped queries, migration, and a concurrent-run test (SQLite file + Postgres) |
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

## Review round 2 (2026-10-20, ~17:20 IST), external review of bed9ea3
| # | Item | Result |
|---|---|---|
| R1 | Tests on a fresh clone | D5 tests that need `/workspace/indiatrader` skip cleanly (`needs_india`). Verified: `git clone` to `/tmp/tcclone` with `INDIATRADER_ROOT=/nonexistent`, then `scripts/run_all.sh`: 47 passed, 6 skipped, 5/5 drills PASS, server started |
| R2 | Docker | `Dockerfile` (python:3.13-slim, uid 10001 non-root, no secrets) + `docker-compose.yml` (app, postgres:17-alpine, redis:7-alpine) + `.env.example`. Built OK with docker 26.1.5 on this box; the container served `/api/summary` on SQLite. **Not verified:** `docker compose` (plugin not installed here), and app→Postgres inside Docker (container-to-container TCP timed out in this sandbox although DNS resolved). Redis is provisioned, but the runtime engine uses no bus (only the drills use InProcessBus), so the app does not use Redis yet |
| R3 | CI | `.github/workflows/ci.yml`: pytest with a postgres:17 service (`TEST_DATABASE_URL`), drills, paper day. **Never run on GitHub** (nothing pushed) |
| R4 | Pins | `requirements.txt` has exact pins; `requirements.lock` is the full `pip freeze` |
| R5 | Generated reports | `reports/*` gitignored except `AUDIT.md` and `reports/examples/` (3 examples); earlier runtime files untracked with `git rm --cached` (still in history) |
| R6 | Auth | Bearer header only; `?token=` is ignored and stripped from the URL by the UI; sign-in form keeps the token in sessionStorage. WebSocket uses first-message auth `{"auth": token}` within 5 s, with no query fallback. Optional owner TOTP (`CREW_OWNER_TOTP_SECRET`, pyotp) for approve/mode/config, sent as the `X-TOTP` header; off when unset. `run_all.sh` no longer prints tokens; generated ones go to `var/session.env` (0600) |
| R7 | Frontend tests | `tests_e2e/test_ui_smoke.py`: 17 pages + a login/URL-token test, run with `/workspace/.pwvenv`: 18 passed |
| R8 | Agents | Before: 20 of 35 enabled agents were never invoked, and 3 (S43, S45, S10) made cosmetic calls. Now 34 are enabled; S16 Calibrator is `DISABLED_IDLE` because the fixture has no resolved outcomes. **32 of 34 enabled agents are invoked per paper day.** S34 runs only on a risk veto (0 in this run); S15 runs on backtests. Post-run monitors (S11, S29, S30, S31, S32, S33, S42, S44, S17) measure and record only; they are not in the trade decision path |
| R9 | DB connect | added `connect_timeout` (default 10 s) so an unreachable `DATABASE_URL` fails instead of hanging boot (found during the Docker test) |

## Round 3 (2026-10-20, ~18:15 IST), roadmap items
| Item | Result |
|---|---|
| run_id isolation | done; AUDIT #14 FIXED. Concurrent schema init needed an in-process lock (SQLite) and an advisory lock (Postgres); both races were found by the new tests |
| LLM metering | done; prices only from `config/llm_pricing.json` (source and date recorded); unknown => UNKNOWN; AUDIT #13 FIXED. **Not verified against a real provider response** (no key) |
| Prometheus `/api/v1/metrics` | done; auth-protected. Bus DLQ gauge comes from the drill bus, because the runtime engine has no bus |
| Order book + staleness guard | done, offline only; the guard is wired into D4 signal evaluation and never fires on the gap-free fixture (results unchanged) |
| Lightweight Charts + utilisation heatmap | done; vendored v5.2.1 with LICENSE and a NOTICE (the upstream package has no NOTICE file, so ours records the attribution) |
| New assumption | `config/feed_guard.json` thresholds (120 s gap, 5 s drift) are engineering defaults, not verified exchange guidance |
