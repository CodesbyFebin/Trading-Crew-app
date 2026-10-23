# Trading Crew live-gate assessment

**Assessment date:** 2026-10-23
**Scope:** Binance Spot D4, authenticated exchange execution
**Decision:** **BLOCKED — do not enable live orders**

This report records repository evidence only. A public market-data connection is not an authenticated account connection and does not qualify an execution system.

| Gate | Status | Evidence / remaining work |
|---|---|---|
| Public live market data | PASS (data only) | Binance public REST/WebSocket feed was exercised through the app: 63 stream messages, a fresh BTC quote, 500 one-minute candles, zero rejected messages. Feed reports account and order execution unavailable. Round 10 in `reports/AUDIT.md`. |
| Strategy qualification | FAIL | The only bundled D4 strategy uses synthetic replay data. Latest paper artifact covers 2.999 synthetic days, 12 round trips, 2 winners, and net PnL **-3.6518 USDT** after modeled costs. It is neither a verified live-data paper run nor evidence of an edge. |
| Historical/out-of-sample validation | NOT PASSED | Backtest provenance says synthetic, about three days, two symbols and only 12 round trips; independent historical holdout evidence is absent. See `reports/backtests-latest.json`. |
| 30-day paper qualification | NOT PASSED | No qualifying 30-day paper record exists. The available paper artifact is approximately three days and synthetic. |
| Authenticated exchange account | NOT CONFIGURED | No Binance API key or secret was present in the environment at assessment time. No account permission or balance check was performed. |
| Production live order connector | NOT IMPLEMENTED | `crew.connectors.LiveAdapter` raises `LiveDisabled` before network access. No production account stream, order submission, cancellation, fill reconciliation, or exchange-side kill path exists. |
| Binance Spot Testnet client | PASS (local contract tests only) | `crew/binance_testnet.py` is a standalone fixed-host Testnet REST client, with Decimal filter validation, signed requests, client-order IDs, query/cancel endpoints, and ambiguous-timeout handling. It is not connected to strategy routing. No Testnet credentials or remote order lifecycle have been verified. |
| Mode promotion | BLOCKED | The permanent PAPER-only cap has been removed. `LIVE_ENABLED` is false by default; the API has no trusted evidence source and passes empty stats, so promotion fails closed until evidence and signed owner approval are available. |
| Backend readiness checklist | PASS (reporting only) | `GET /api/execution/gates` now computes current statuses from the live feed, D4 provenance/results, drill report, approvals and execution connector. This reports blockers; it does not qualify or enable live execution. |
| Local risk/kill drills | PASS (local only) | All six drills pass, including kill, drawdown, demotion, tamper, bus chaos and daily-loss kill. These drills do not test exchange positions or orders. `reports/drills-latest.json`. |
| Exchange reconciliation and emergency controls | NOT TESTED | No authenticated account/order channel is configured, so live position reconciliation, cancel/flatten behavior, timeout recovery and duplicate-order handling have no evidence. |
| Owner approval | NOT PRESENT | No verified live-promotion approval was supplied or recorded. |
| India D5 / Fyers | ARCHIVED | D5 remains research/checks-only. Fyers algo-desk confirmation and static IP prerequisites remain outstanding; this assessment does not change its status. |

## Result

The live market-data gate is qualified. The authenticated account, strategy, paper-duration, reconciliation, live-order, and owner-approval gates are not. Mode promotion now uses measurable supervised-live and risk conditions rather than a permanent hard cap, but the current API has no evidence source and the connector still has no venue execution client. The available strategy evidence is negative and synthetic. Do not mark this application live-ready or route strategy signals to an exchange.

## Engineering verification

The isolated Binance Spot Testnet client is covered by offline tests for HMAC request signing, fixed Testnet host, Decimal-only quantity and price validation, exchange filter enforcement, limit-only order payloads, client-order-ID reconciliation after an ambiguous timeout, and missing-credential rejection. The full repository suite passed **209 tests, with 9 skipped** on 2026-10-23. Compile checks, JavaScript syntax checks, and `git diff --check` also passed. These results verify local code contracts; they do not represent an authenticated Testnet session or completed live-trading gates.

No API secret should be pasted into chat or committed. Any later account integration needs a dedicated least-privilege key, exchange-specific permission review, an approved strategy and independently verified paper evidence before order execution is considered.
