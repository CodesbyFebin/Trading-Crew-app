# End-to-end trading lifecycle

**Status:** target lifecycle contract and implementation map, assessed 2026-10-24. This document defines coverage; it does not certify production execution or a profitable strategy.

Trading Crew should automate the operating loop from market events through post-trade evidence. Each stage consumes typed, timestamped inputs and emits an auditable result. Unknown, stale, malformed, or unreconciled state blocks new risk.

## Lifecycle

| Stage | Required behavior | Fail-closed behavior |
|---|---|---|
| 1. Market data | Ingest venue public quotes/trades/candles. Separately ingest authenticated account, order, and fill events only when a venue adapter is qualified. Preserve event time, receive time, source, symbol, sequence/revision, and correlation ID. | Disconnect, stale stream, sequence gap, timestamp drift, unsupported symbol, or malformed payload marks data unavailable. Never substitute a plausible value. |
| 2. Data checks | Validate schema, decimal precision, monotonic timestamps, duplicate/out-of-order events, gaps, OHLC relationships, venue filters, symbol status, and source freshness. Record rejects and quarantine the affected stream/instrument. | A failed check marks the affected data unusable and blocks dependent signals. Recovery requires a fresh snapshot and valid sequence continuity. |
| 3. Research and signals | Run versioned deterministic features and strategy rules against a named data snapshot. Emit a signal with strategy/version, input window/hash, rule evidence, expiry, and intended side/size basis. LLM output may annotate research only. | Missing provenance, look-ahead leakage, expired signal, unsupported regime, or failed validation yields no order intent. |
| 4. Deterministic risk approval | Recompute size and exposure from current equity, open positions, pending orders, fees/slippage assumptions, venue limits, daily/weekly loss, drawdown, concentration, liquidity, cooldown, mode, and kill state. Use Decimal arithmetic. Bind approval to the exact intent and limits hash. | Risk authority is the final veto. Strategy, UI, and LLM cannot weaken limits or reuse approval for a changed intent. Timeout, tampering, or unknown portfolio state means reject. |
| 5. Order handling | Convert only an approved, unexpired intent into an idempotent client order. Validate venue filters and product/mode before submission. Track acknowledgements, partial fills, cancel/replace, rejects, expiry, and ambiguous timeouts. Query by client ID before retrying an uncertain submission. | Never blindly retry an ambiguous order. No new entry while order state is uncertain. Testnet and production credentials/endpoints must be isolated. |
| 6. Position monitoring and exits | Build positions only from confirmed fills. Subscribe to account/order events and periodically compare with a fresh venue snapshot. Mark positions from validated market data; evaluate protective exits and time limits independently of entry logic. | Stale marks or broken account stream freeze entries. A kill first blocks new orders and cancels pending entries; position closure follows only a separately tested, venue-specific policy. |
| 7. Reconciliation | Compare internal orders, fills, fees, cash, and positions against venue records using stable IDs and exact decimals. Persist differences and their resolution. Resume only after account state is consistent. | Any unexplained quantity, cash, fee, or order-status drift halts new entries and raises a critical event. No silent ledger repair. |
| 8. Audit and alerts | Append every source event reference, check, signal, risk decision, approval, order transition, fill, position mark, reconciliation result, kill, and operator action with UTC time, run/correlation IDs, component version, and sanitized detail. Alert on critical failures and verify delivery. | Secrets never enter logs. Audit-store or alert-delivery failure is visible and cannot be reported as healthy; unresolved critical events keep the system halted. |

## Event and transition contract

Each lifecycle record should carry, where applicable:

- `event_id`, `run_id`, `correlation_id`, `event_type`, `occurred_at`, and `received_at`;
- source/venue, instrument, schema version, and source sequence or revision;
- strategy and configuration version, limits hash, and provenance references;
- a typed payload with Decimal values serialized as decimal strings;
- outcome state and a stable reason code for every rejection or failure.

An order intent is immutable once risk-approved. Any material change to symbol, side, quantity, limit, expiry, strategy version, or account snapshot creates a new intent and requires a fresh risk decision. Persist event transitions append-only; use idempotency keys for retries and correlation IDs across restarts.

## Current implementation and evidence

| Stage | Current repo evidence | Remaining qualification |
|---|---|---|
| Market data | Public Binance Spot REST/WebSocket stream exercised; read-only and display-only. | It is not connected to strategy inputs or portfolio accounting. Authenticated account/order streams are absent. |
| Data checks | Schema/freshness checks exist for the public feed and replay inputs. | Demonstrate one coherent live snapshot-to-signal data path and recovery after gaps. |
| Research/signals | Deterministic features and the D4 EMA/regime replay exist. | Current strategy evidence is synthetic, short, and negative after modeled costs; no edge is qualified. |
| Risk approval | Decimal-only risk engine, limits integrity checks, kill/drawdown drills, and owner-approval/mode gates exist. | These are local/replay controls; they have not been validated against a live account or venue state. |
| Order handling | Binance Spot Testnet REST client has offline contract tests and is separate from strategy routing. | No remote testnet order lifecycle has been verified; production connector is not implemented. |
| Positions/exits | Replay/paper engine tracks fixture positions and mark-to-market risk. | No authenticated position monitor or exchange-side exit/flatten path is qualified. |
| Reconciliation | Internal paper/replay ledger reconciliation is exercised. | Exchange orders, fills, fees, balances, and positions have not been reconciled against a venue account. |
| Audit/alerts | Append-only local audit trail and safety drills are covered by tests. | End-to-end venue event capture, durable production alert delivery, and operational recovery remain unqualified. |

The authoritative dated status and gate evidence is [`reports/LIVE_GATES.md`](../reports/LIVE_GATES.md). The testnet client’s contract tests and the local drills do not substitute for remote account/order lifecycle evidence.

## Verification needed for each stage

Before any venue execution is considered, qualification should include:

1. Recorded provenance and deterministic replay from market-data event through signal and risk decision.
2. Fault injection for stale data, gaps, duplicates, disconnects, rate limits, and clock skew.
3. Testnet order placement, partial fill, cancel, reject, timeout, query-by-client-ID, restart recovery, and duplicate suppression.
4. Position and cash reconciliation after every testnet lifecycle, including fees and partial fills.
5. Kill-switch drills with open and pending orders, followed by verified account reconciliation.
6. Durable audit and alert checks, with secret scrubbing and a tested alert-delivery failure path.
7. Independent review of venue permissions, static-IP requirements, broker/exchange rules, deployment security, and the exact promotion evidence.

Passing one stage does not qualify the next. Do not claim live readiness until the current live-gate report records the evidence and all required owner approvals.
