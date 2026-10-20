# Changelog
All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased] - 2026-10-20
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
