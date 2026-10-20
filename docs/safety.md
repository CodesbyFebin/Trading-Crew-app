# Safety

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

![Risk Console](assets/risk_console.png)

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

## Audit summary and known limitations

The full audit, with file and line references, is in [`reports/AUDIT.md`](https://github.com/CodesbyFebin/Trading-Crew-app/blob/main/reports/AUDIT.md). It lists 35 items:
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
