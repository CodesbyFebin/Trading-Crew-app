# API

## API reference

Every endpoint requires `Authorization: Bearer <token>`. Owner actions additionally need `X-TOTP` when TOTP is enabled.
JSON Schemas for all request bodies and typed models are in [`schemas/`](schemas.md) (draft 2020-12).

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
| GET | `/api/skills` | view | skills catalog |
| POST | `/api/skills/{name}` | owner/operator (`research`) | execute a deterministic local skill (argument JSON limited to 16 KiB) |
| GET | `/api/llm` | view | router status and recent calls |
| POST | `/api/jev` | view | ask JEV (advisory) |
| GET | `/api/v1/metrics` | view | Prometheus text format |
| GET | `/api/candles?symbol=&interval=` | view | OHLC of the replay mid price plus paper fills |
| GET | `/api/risk/utilisation` | view | per-limit utilisation (last check and peak) |
| WS | `/ws/{summary,agents,trace}` | view | live updates; first message `{"auth": token}` |
