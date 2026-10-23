# Architecture

## Mode ladder

`REPLAY → PAPER → LIVE_APPROVAL → LIVE_AUTO` (`crew/modes.py`)

- Promotion moves **one rung at a time**, and each step has a pure gate function over recorded statistics
  (out-of-sample net expectancy, calibration, number of paper days, reconciliation drift, kill-drill result, slippage within
  model).
- Any promotion beyond PAPER also needs a valid **signed owner approval**.
- The API **cannot set any mode above PAPER** in this build.
- **Live modes are unreachable.** The hard mode gate refuses every transition above PAPER, regardless of environment variables or signed approvals.
- `LIVE_ENABLED=false` is the default; the mode gate hard-denies promotion beyond PAPER regardless of environment configuration.
- Any breach **auto-demotes one rung**. The auto-demotion drill shows LIVE_APPROVAL → PAPER → REPLAY.

## Desks

| Desk | What | Data | Status |
|---|---|---|---|
| D4 | Crypto signals (Binance-style spot) | Strategy input: synthetic `fixtures/binance_replay_sample.jsonl`; separate display feed: Binance public Spot REST/WebSocket | PAPER/REPLAY only; live public quotes are display-only and do not enter decisions or accounting |
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

## Regime research and Jules Crew evolution

The next increment adds a **replay-only Regime Research layer** (`crew/regimes.py`). It classifies each D4 feature row using:

- Trend direction from the existing EMA slope signal (`TREND_UP`, `TREND_DOWN`, `CHOP`).
- Volatility and spread states compared with trailing per-symbol medians. The current row is excluded from its own baseline; the first 20 observations are `UNKNOWN`.
- An entry-regime label attached to each simulated position, then a closed-trade summary by label in `GET /api/pnl` and the Command Center.

These labels are descriptive. They do not select, enable, disable, or tune strategies; they do not enter the Risk Engine; and they do not call an LLM or a network service. The sample remains synthetic and short, so regime groups cannot establish predictive value. D4's frozen strategy behavior and D5's archived/checks-only status remain unchanged.

### Jules Crew design mapped to this repository

| Proposed subsystem | Current foundation | Next safe work | Explicitly outside this build |
|---|---|---|---|
| Hard Risk Kernel | `crew/risk.py`: deterministic Decimal checks, immutable file limits, tamper hash, timeout fail-closed | Keep adversarial tests and tighten measured behavior | Rust process, hardware enforcement, exchange-state polling |
| Conductor | `crew/engine.py`, `crew/agents.py`, `crew/bus.py`: deterministic orchestration and structured typed events | Test bounded retries, persisted recovery, and failure isolation in replay | Dynamic agent spawning or LLM arbitration |
| Regime Intelligence | D4 trend signal plus new causal replay labels and regime-stratified results | Add richer features only when source data and methodology are documented; keep held-out evaluation | Automatic strategy router or market-state claims from synthetic data |
| Execution Fabric | S35 routes only to S36 paper fills; `LiveAdapter` raises before network access | Improve deterministic replay latency measurement and paper reconciliation | Live exchange routing, DMA/FIX, co-location, latency promises |
| Data Fabric | Local fixtures, schema validation, staleness guard, append-only reports and memory | Add replay provenance, corruption checks, and causal feature tests | Live/testnet feeds while repository policy forbids them |
| Learning loop | Append-only shared memory, backtest grid, paper reports | Store proposed research as advisory and require explicit offline validation | Auto-applying strategy changes or automatic promotion |
| Custody/compliance | No wallet signing or order connectors; D5 Gate 0 is locked | Keep explicit “NOT CONFIGURED” states and audit trail | MPC signing, withdrawals, broker keys, or a claim of SEBI certification |

### Build roadmap

1. **Replay measurements (implemented):** causal trend/volatility/spread labels, realized P&L summaries by entry regime, tests for look-ahead and Decimal accounting.
2. **Research validation (implemented):** the fixed six-variant grid is evaluated across independent chronological 60/20/20 windows. Features warm up on prior rows, but fills are restricted to each window; every variant and fold is reported with source SHA-256, costs, open-position marks and reconciliation drift. This is not evidence of edge or approval.
3. **Resilience in replay (implemented):** existing QA rejects duplicate, crossed, non-trading and out-of-order rows; staleness blocks signals after gaps. The append-only global audit journal restores an engaged kill after process restart, while an owner-signed reset is explicitly journaled and authenticated by the API.
4. **Operational hardening:** retain append-only evidence, resource limits, service health checks, and owner-visible failure states; test on the target host before making performance claims.

Rust HRK isolation, sub-millisecond execution targets, multi-venue routing, MPC custody, automatic adaptation and live trading remain proposals. A read-only public Binance Spot feed is implemented for display; the repository prohibits live/testnet order connectors and wallet signing. The paper engine remains replay-only.

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
