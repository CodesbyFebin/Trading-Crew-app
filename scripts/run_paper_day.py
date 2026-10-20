"""End-to-end paper run on the replay sample + D1-D3 synthetic desks + D5 India check replay. Writes the S47 honest report."""
import json, sys, datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from crew.engine import CrewSystem
from crew import desk_d5
sysm = CrewSystem(str(ROOT/"reports"/f"ledger-{datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5,minutes=30))):%Y%m%d-%H%M%S}.db"))
r = sysm.run_paper_day()
try: r["D5"] = {"replay": desk_d5.replay(), "sebi": desk_d5.sebi_gates(desk_d5.OwnerSignals())}
except Exception as e: r["D5"] = {"error": str(e)}
d = r["D4"]; stamp = f"{datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5,minutes=30))):%Y%m%d-%H%M%S}"
(ROOT/"reports"/f"paper-day-{stamp}.json").write_text(json.dumps(r, indent=1, default=str))
d5 = r["D5"].get("replay", {})
md = f"""# Honest report (S47) — {stamp} IST

**Mode:** {r['mode']} only. No live orders exist. Trading can lose all capital; no profitability is claimed.

## D4 crypto signals (Binance replay sample)
- Source: {d['source']} (sha256 `{d['source_sha256'][:16]}…`), span {d['span_days']} days of 1-minute snapshots.
- Data QA: {d['qa']}
- Start equity {d['start_equity']} USDT → final (marked to bid) {d['final_equity_mtm']} USDT.
- **Net PnL after fees and slippage: {d['net_pnl_after_costs']} USDT.** Fees paid {d['fees_paid']}; avg slippage {d['avg_slippage_bps']} bps.
- Fills {d['fills']}, round trips {d['round_trips']}, winning {d['winning_round_trips']}. Sample is far too small to infer any edge.
- Risk vetoes: {len(d['vetoes'])}. Reconciliation drift: {d['reconciliation_drift']}.
- Daily realized PnL: {d['daily_pnl_realized']}
- Daily mark-to-market PnL ({d['day_boundary']}): {d['daily_pnl_mtm']}
- Provenance: {d['provenance']['data_status']} (verified historical: {d['provenance']['verified_historical']}), {d['provenance']['time_range_utc'][0]} → {d['provenance']['time_range_utc'][1]}
- Assumptions: {d['provenance']['assumptions']}
- Limitations: {'; '.join(d['provenance']['limitations'])}
- Ticket outcomes: {r['ticket_outcomes']} ; escalations {r['escalations']} ; trace rows {r['trace_rows']}
- Strategy variants tried (counted against chance): {r['strategy_variants_tried']}
- Cost: {r['cost']}
- Agents invoked this paper day: {len(r['agents_invoked'])} ({', '.join(r['agents_invoked'])})
- Post-run monitors (not in the decision path): {r['agent_work']}
- S26 brief: {r['brief']}

## D1/D2/D3 — SYNTHETIC FIXTURES, NOT_APPROVED_BY_OWNER, REPLAY-locked
No trades. Outputs are rule checks on made-up fixtures, not results.

## D5 India NSE — {desk_d5.STATUS}
No strategy run. Check replay over {d5.get('sessions')} bhavcopy sessions ({d5.get('first')} → {d5.get('last')}):
universe ok {d5.get('universe_ok')}, fail {d5.get('universe_fail')}; pre-universe date {d5.get('pre_universe_date')};
calendar: {d5.get('production_calendar')}. SEBI gates may_leave_replay = {r['D5'].get('sebi',{}).get('may_leave_replay')}.
"""
(ROOT/"reports"/f"paper-day-{stamp}.md").write_text(md); print(md)
