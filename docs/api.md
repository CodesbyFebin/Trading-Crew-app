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
| GET | `/api/pnl`, `/api/markets`, `/api/research` | view | paper PnL and equity curve, descriptive D4 replay outcomes grouped by entry regime; fills and QA; D1–D3 fixture output |
| GET | `/api/reports`, `/api/reports/{name}` | view | generated reports |
| GET | `/api/risk`, `/api/drills` | view | limits, hash, kill state, risk events, drills |
| POST | `/api/drills/run` | operator | re-run the safety drills |
| GET/POST | `/api/connectors`, `/api/connectors/{name}/test` | view | connector health and contract tests |
| GET/POST | `/api/configs`, `/api/configs/rollback/{ver}` | owner | versioned config (risk limits are rejected) |
| GET/POST | `/api/mode` | owner | mode ladder (API capped at PAPER) |
| POST | `/api/kill` | operator | engage the kill switch |
| POST | `/api/kill/reset` | owner | HMAC-signed kill reset; also requires `X-TOTP` when configured |
| GET/POST | `/api/approvals` | owner | signed approvals |
| GET | `/api/audit` | view | audit log |
| GET / POST | `/api/backtests`, `/api/backtests/run` | view / owner | S15 grid backtests |
| GET | `/api/memory` | view | shared memory |
| GET | `/api/skills` | view | skills catalog |
| POST | `/api/skills/{name}` | owner/operator (`research`) | execute a deterministic local skill (argument JSON limited to 16 KiB) |
| GET | `/api/llm` | view | router status and recent calls |
| POST | `/api/jev` | view | ask JEV (advisory) |
| GET | `/api/v1/metrics` | view | Prometheus text format |
| GET | `/api/candles?symbol=&interval=` | view | OHLC of the synthetic replay mid price plus paper fills |
| GET | `/api/market-data` | view | current public read-only Binance Spot quotes and feed health; no account data |
| GET | `/api/market-data/candles?symbol=&interval=&limit=` | view | public live Spot candles; separate from replay and paper metrics |
| GET | `/api/risk/utilisation` | view | per-limit utilisation (last check and peak) |
| WS | `/ws/{summary,agents,trace,market_data}` | view | authenticated updates; first message `{"auth": token}`; market_data is public exchange data only |

## Market-data API boundary

`/api/market-data` returns source, connection status, subscribed symbols, best bid/ask, latest trade, data age, stale flags, reconnect count and errors. `/api/market-data/candles` supports allowlisted symbols and intervals of 60, 300, 900 or 3600 seconds, with a maximum of 1,000 rows. The WebSocket `market_data` channel sends the same read-only snapshot. All three routes require normal viewer authentication. They never expose or access account balances, positions, private streams or order functions.
