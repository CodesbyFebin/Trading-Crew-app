# API

## API reference

Every endpoint requires `Authorization: Bearer <token>`. Owner actions additionally need `X-TOTP` when TOTP is enabled.
JSON Schemas for all request bodies and typed models are in [`schemas/`](schemas.md) (draft 2020-12).

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/api/whoami` | view | your role |
| GET | `/api/summary` | view | header stats (mode, paper PnL, fees, fills, kill state, LLM cost) |
| GET | `/api/agents` | view | the 50 named roles (deterministic Python functions, not independent AI agents) with call metrics |
| GET | `/api/desks`, `/api/india` | view | desk status; D5 Gate 0, SEBI checklist and replay |
| GET | `/api/tickets`, `/api/trace` | view | ticket state machine history; append-only trace |
| GET | `/api/pnl`, `/api/markets`, `/api/research` | view | paper PnL and equity curve; fills and QA; D1–D3 fixture output |
| GET | `/api/reports`, `/api/reports/{name}` | view | generated reports |
| GET | `/api/risk`, `/api/drills` | view | limits, hash, kill state, risk events, drills |
| POST | `/api/drills/run` | operator | re-run the safety drills |
| GET/POST | `/api/connectors`, `/api/connectors/{name}/test` | view | connector health and contract tests |
| GET/POST | `/api/configs`, `/api/configs/rollback/{ver}` | owner | versioned config (risk limits are rejected) |
| GET/POST | `/api/mode` | owner | mode ladder; promotions require evidence and signed approval; no live-evidence source is wired |
| POST | `/api/kill` | operator | engage the kill switch |
| POST | `/api/kill/reset` | owner | clear the kill with an HMAC-signed approval (and TOTP when configured) |
| GET/POST | `/api/approvals` | owner | signed approvals |
| GET | `/api/audit` | view | audit log |
| GET / POST | `/api/backtests`, `/api/backtests/run` | view / owner | S15 grid backtests |
| GET | `/api/memory` | view | shared memory |
| GET | `/api/skills` | view | skills catalog |
| POST | `/api/skills/{name}` | owner/operator (`research`) | execute a deterministic local skill (argument JSON limited to 16 KiB) |
| GET | `/api/llm` | view | router status and recent calls |
| POST | `/api/jev` | view; `save_note` needs operator/owner | ask JEV (advisory text only); rate- and budget-limited |
| GET | `/api/jev/budget` | view | LLM usage counters and limits (no keys) |
| POST | `/api/research/ta` | operator/owner (`research`) | optional TA research desk; off unless `CREW_RESEARCH_TA=1`; LLM text only |
| GET | `/api/v1/metrics` | view | Prometheus text format |
| GET | `/api/candles?symbol=&interval=` | view | OHLC of the replay mid price plus paper fills |
| GET | `/api/market-data`, `/api/market-data/candles` | view | live public Binance Spot quotes/candles; read-only and separate from execution |
| GET | `/api/execution/status` | view | actual venue-client/account/order readiness; `LIVE_ENABLED` alone never marks execution ready |
| GET | `/api/execution/gates` | view | server-computed live readiness checklist and evidence state |
| GET | `/api/risk/utilisation` | view | per-limit utilisation (last check and peak) |
| WS | `/ws/{summary,agents,trace,pnl}` | view | live updates; first message `{"auth": token}` (tokens in URLs are ignored) |

Every mutating route (`/api/mode`, `/api/configs`, rollback, `/api/approvals`, `/api/kill`, `/api/drills/run`,
`/api/backtests/run`, JEV notes) writes an audit row, including rejected mode changes. D4 responses (`/api/summary`,
`/api/pnl`, `/api/markets`, `/api/candles`, `/api/book`), reports and backtests carry a `provenance` block: source,
sha256, `data_status: SYNTHETIC_REPLAY`, `verified_historical: false`, UTC time range, labelled assumptions (fee rate
ASSUMED, slippage MODELLED from synthetic L2, funding NOT MODELLED) and limitations.

**Exposure.** All launchers bind to `127.0.0.1` by default (`scripts/run_all.sh`, `docker-compose.yml` maps
`127.0.0.1:8795`, the desktop app only uses `0.0.0.0` with `--lan`). The app speaks plain HTTP. If you expose it beyond
localhost, put it behind a TLS-terminating reverse proxy (for example Caddy or nginx) on a trusted network, and use long
random tokens; bearer tokens over plain HTTP on a LAN can be sniffed.
