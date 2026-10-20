# Architecture

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
