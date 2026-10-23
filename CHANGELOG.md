# Changelog
All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased] - 2026-10-24
### Added
- Read-only Binance Spot public REST/WebSocket feed for live quotes and candles, status/freshness, reconnects, and authenticated API/UI delivery. Feed is isolated from strategy evaluation, paper fills, risk state and PnL; no account or order integration.
### Changed
- Migrated FastAPI service startup and feed cleanup to the lifespan lifecycle, including cleanup if startup fails.
- Corrected Binance Spot `bookTicker` parsing for the documented payload shape (no `e` field); expose bounded rejection diagnostics for unexpected stream messages.
### Added (2026-10-23)
- Fixed chronological S15 train/validation/holdout replay windows for all six parameter variants; per-fold source provenance, QA, costs, open-position marks and reconciliation.
- Durable kill-state recovery across restarts via the append-only audit journal, plus an owner-only HMAC/TOTP reset route and dashboard control.
- Deterministic replay-chaos tests for duplicate, reordered, crossed, halted, gap and stale feed cases.
### Added / changed (round 4)
- Automatic daily-loss kill through the same path as the API kill; kill/fill serialisation; `daily_loss_kill` drill (6 drills).
- PAPER hard cap above the existing LIVE_APPROVAL checks; API hardening (health endpoints, bounded queries, `research` permission and 16 KiB cap for skills, WebSocket permission and channel allowlist).
- Postgres append-only triggers created only if missing; single-worker risk check.
- Stricter replay tick validation and connector contract; no-lookahead test.
- Batch SLA (10 s) for S01/S09/S10, fixing the intermittent concurrent-run failure; `websockets` pinned so `/ws/*` works under uvicorn.
- CI fails if the Postgres tests are skipped.
### Added (round 3)
- `run_id` isolation for all ledger/store tables (SQLite + Postgres) with migration and concurrent-run tests.
- LLM usage metering (provider `usage`; verified free prices; UNKNOWN otherwise).
- Prometheus metrics at `/api/v1/metrics` (auth-protected).
- Offline L2 order book and feed-staleness / clock-drift guard (`crew/orderbook.py`, `config/feed_guard.json`).
- Lightweight Charts candlesticks with fill markers; risk-limit utilisation heatmap; `/api/candles`, `/api/risk/utilisation`.
- Schema for `L2Book` (27 schemas); `AdvisoryNote` gains token and cost fields.
### Added
- Open-source files: LICENSE (MIT), CONTRIBUTING, CODE_OF_CONDUCT (Contributor Covenant 2.1), SECURITY, issue/PR templates, FUNDING, AGENTS.md, llms.txt.
- JSON Schemas (draft 2020-12) for 26 typed models in `schemas/`, with a validation test.
- MkDocs documentation site published to GitHub Pages; favicon and social meta tags.
- Detailed README.

## [0.3.0] - 2026-10-20: review fixes
- Fresh-clone-safe tests (D5 skips without the archived project); Dockerfile, docker-compose (app, postgres, redis); CI workflow.
- Pinned dependencies (`requirements.txt`, `requirements.lock`); runtime reports untracked.
- Header-only auth, WebSocket first-message auth, optional owner TOTP; Playwright smoke tests.
- Agents wired to real offline work: 32 of 34 enabled agents invoked per paper day; S16 set to DISABLED_IDLE.

## [0.2.0] - 2026-10-20: audit and brain layer
- `reports/AUDIT.md`; real Postgres and Redis Streams adapters; SQLite write lock.
- Shared append-only memory; 15 deterministic trading skills; S15 backtests API.
- Advisory-only LLM router (OpenRouter, Kilo, Groq, Cline) and the JEV assistant.

## [0.1.0] - 2026-10-20: initial
- Paper-only multi-agent platform: risk engine, kill switch, mode ladder, append-only ledger, D1–D5 desks, dashboard, drills.
