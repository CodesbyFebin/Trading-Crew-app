# AGENTS.md: guide for AI coding agents

This repository is a **paper-only** trading research platform. Read this whole file before changing anything.

## Hard safety rules (never weaken, never bypass, never "temporarily" disable)
1. **No live trading.**
   - Do not add live or testnet market-data or order connectors, exchange SDKs, wallet signing or withdrawal code.
   - `LIVE_ENABLED` stays `false`.
   - `LiveAdapter` must keep raising before any network code.
2. **LLMs never decide trades or risk.**
   - Crew agents, the overseer (`crew/overseer.py`), the risk engine, modes and the kill switch are deterministic Python.
   - LLM output (`crew/llm_router.py`, `crew/jev.py`) is advisory text only and must never be imported by order, risk or
     mode code. `tests/test_brain.py::test_no_llm_path_reaches_order_risk_mode_code` must keep passing.
3. **Risk limits are file-only and immutable at runtime** (`config/limits.json` + SHA-256 + `LimitsAuditor`).
   - Comparisons treat at-limit as a breach.
   - The engine fails closed on timeouts, exceptions and bad types.
   - Money is `Decimal` only.
4. **Mode ladder.**
   - The API cannot exceed PAPER, and LIVE_AUTO stays unreachable.
   - Promotion beyond PAPER needs an HMAC-signed owner approval.
   - Breaches auto-demote.
5. **Append-only storage.** Never remove the UPDATE/DELETE triggers or add code that mutates the ledger, trace, audit log or
   shared memory.
6. **Secrets.**
   - No keys or tokens in code, tests, docs, commit messages, command-line arguments or URLs.
   - Use `.env` (gitignored); `.env.example` holds empty values.
   - Auth is `Authorization: Bearer` only, and the WebSocket uses first-message auth.
7. **Desks.**
   - D1, D2 and D3 are locked to REPLAY.
   - D5 India is archived and checks-only, with Gate 0 terms unchanged.
   - Track 1 (D4) strategy logic is frozen until the owner approves the paper logs.
8. **Honesty.**
   - No fabricated numbers, fake agent calls, fake LLM responses or invented model IDs.
   - Label synthetic data as synthetic, and show "NOT CONFIGURED" when something is not configured.
   - Report every backtest variant tried.

## Layout
- `crew/`: engine, agents, overseer, risk, modes, killswitch, store, memory, bus, connectors, desks (`desk_d4`,
  `desks_synthetic`, `desk_d5`), skills, backtest, llm_router, jev and api (FastAPI).
- `web/`: dashboard. `config/`: limits and LLM routing. `fixtures/`: synthetic data. `schemas/`: JSON Schemas.
- `tests/` (pytest), `tests_e2e/` (Playwright), `scripts/`, `docs/` (MkDocs), `reports/AUDIT.md`.

## Commands
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock
.venv/bin/pytest -q tests                    # must pass; D5 and Postgres tests skip when their resources are absent
.venv/bin/python scripts/run_drills.py       # all 5 drills must PASS (exit code 0)
.venv/bin/python scripts/gen_schemas.py      # regenerate schemas after changing a typed model
scripts/run_all.sh                           # full local run + server on 127.0.0.1:8795
```

## Test requirements for any change
- Add or extend tests for new behaviour. Never delete or loosen safety tests to make a change pass.
- Keep `tests/test_schemas.py` green; it fails when the schemas are stale.
- UI changes: run `tests_e2e` (no console errors on any page).
- Update `reports/AUDIT.md` when you add, fix or discover a stub, mock or assumption.
