"""Wires everything: overseer, crew agents, risk engine, kill switch, ledger, D4 paper run, D1-D3 replay desks."""
from __future__ import annotations
import asyncio, time
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path
from .agents import Registry
from .connectors import BinanceReplay, all_connectors
from .desks_synthetic import DESKS, run_d1, run_d2, run_d3
from .desk_d4 import s01_tape, s09_dataqa, s10_features, s14_regime, s27_size, s36_paper_fill, day_of, FEE_RATE, book_walk
from .killswitch import KillSwitch
from .models import TicketState as S, RiskEvent, ConfigStore
from .modes import ModeController, Mode
from .overseer import MainGrok
from .risk import Limits, LimitsAuditor, RiskEngine, OrderIntent, Portfolio
from .store import SQLiteStore

ROOT = Path(__file__).resolve().parent.parent
LIMITS = ROOT/"config"/"limits.json"
START_EQUITY = D("10000")

class CrewSystem:
    def __init__(self, db=":memory:"):
        self.store = SQLiteStore(db); self.reg = Registry(); self.kill = KillSwitch()
        self.limits = Limits(LIMITS); self.auditor = LimitsAuditor(self.limits, LIMITS)
        self.risk = RiskEngine(self.limits, self.kill, self.auditor)
        self.modes = ModeController(); self.main = MainGrok(self.reg, self.store)
        self.config = ConfigStore(); self.config.commit({"limits_sha256": self.limits.sha256, "start_equity": str(START_EQUITY),
                                                         "fee_rate": str(FEE_RATE), "strategy": "ema20/60 cross + regime quorum"}, "system", "boot")
        self.connectors = all_connectors(); self.result: dict = {}; self.approvals: list = []
        self.desks = {"D4": {"desk":"D4","name":"Crypto signals (Binance replay)","status":"PAPER (owner-approved track 1, paper only)"},
                      **{k: {"desk":v.desk,"name":v.name,"status":v.status,"mode":v.mode.value} for k,v in DESKS.items()}}

    def engage_kill(self, reason, actor):
        self.kill.engage(reason, list(self.desks), list(self.main.tickets.values()))
        self.store.append_risk(RiskEvent("KILL", None, reason, "CRITICAL")); self.store.audit(actor, "kill", reason)

    async def _d4(self):
        R, m = self.reg, self.main
        src = BinanceReplay()
        ticks = await R["S01"].run(s01_tape, src.path)
        qa = await R["S09"].run(s09_dataqa, ticks)
        feats = await R["S10"].run(s10_features, list(qa.ticks))
        tick_by = {(t.symbol, t.ts): t for t in qa.ticks}
        cash, pos, fills, equity_curve = START_EQUITY, {}, [], []
        daily, peak, last_loss_ts, vetoes = defaultdict(D), START_EQUITY, None, []
        prev = {}; last_px = {}
        for f in feats:
            t = tick_by[(f.symbol, f.ts)]; last_px[f.symbol] = t
            p0 = prev.get(f.symbol); prev[f.symbol] = f
            if p0 is None: continue
            cross_up = p0.ema_f <= p0.ema_s and f.ema_f > f.ema_s
            cross_dn = p0.ema_f >= p0.ema_s and f.ema_f < f.ema_s
            mtm = cash + sum(q*last_px[s].bid for s,(q,_,_) in pos.items())
            peak = max(peak, mtm)
            if f.ts % 3600 == 0: equity_curve.append((f.ts, str(mtm.quantize(D("0.01")))))
            if cross_dn and f.symbol in pos:
                q, cost, tid = pos.pop(f.symbol); tk = m.tickets[tid]
                fl = await R["S36"].run(s36_paper_fill, tid, t, "SELL", None, q)
                cash += fl.notional - fl.fee; fills.append(fl)
                self.store.append_ledger(self.modes.mode.value, tid, "SELL", fl.notional, fl.fee, f"{f.symbol} exit on cross down")
                pnl = fl.notional - fl.fee - cost; daily[day_of(f.ts)] += pnl
                if pnl < 0: last_loss_ts = f.ts
                tk.transition(S.SETTLED, f"net pnl {pnl.quantize(D('0.0001'))}"); tk.transition(S.AUDITED)
                m.trace(tk, "S44", "C6", "pnl", "RESULT", f"round trip net of fees+slippage: {pnl.quantize(D('0.0001'))} USDT")
            if not cross_up or f.symbol in pos: continue
            tk = m.open_ticket("crypto_signal", f.symbol, "binance")
            tk.transition(S.ENRICHED, "DataQA passed"); tk.transition(S.PRICED, "features computed")
            res = await m.fan_out(tk, {"S10": lambda: "LONG", "S14": lambda f=f: "LONG" if s14_regime(f) == "TREND_UP" else s14_regime(f)})
            if not m.arbitrate(tk, res, "LONG"):
                tk.transition(S.REJECTED, "no quorum agreement"); tk.transition(S.AUDITED); continue
            tk.transition(S.RESEARCHED, "quorum met")
            mtm = cash + sum(q*last_px[s].bid for s,(q,_,_) in pos.items())
            notional = await R["S27"].run(s27_size, mtm)
            try: q_prev = (notional/t.ask); slip = abs(book_walk(t.asks, q_prev)-t.mid)/t.mid*10000
            except Exception: slip = D(9999)
            gross = sum((q*last_px[s].bid for s,(q,_,_) in pos.items()), D(0))
            wk = sum(daily.values(), D(0))
            dec = self.risk.check(OrderIntent(tk.ticket_id, "binance", notional, slip, t.qv24),
                Portfolio(mtm, gross, {"binance": gross}, len(pos), daily[day_of(f.ts)], wk, peak,
                          None if last_loss_ts is None else f.ts - last_loss_ts))
            if not dec.approved:
                tk.transition(S.VETOED, "; ".join(dec.reasons)); tk.transition(S.AUDITED)
                vetoes.append({"ts": f.ts, "symbol": f.symbol, "reasons": list(dec.reasons)})
                self.store.append_risk(RiskEvent("VETO", tk.ticket_id, "; ".join(dec.reasons)))
                m.trace(tk, "S34", "C4", "risk", "VETO", "; ".join(dec.reasons)); continue
            tk.transition(S.RISK_CLEARED); tk.transition(S.APPROVED, "PAPER mode: no human gate for paper fills")
            if not self.kill.allow_new_order(): tk.transition(S.VETOED, "kill switch"); continue
            tk.transition(S.ORDERED)
            fl = await R["S36"].run(s36_paper_fill, tk.ticket_id, t, "BUY", notional)
            cash -= fl.notional + fl.fee; fills.append(fl); pos[f.symbol] = (fl.qty, fl.notional + fl.fee, tk.ticket_id)
            self.store.append_ledger(self.modes.mode.value, tk.ticket_id, "BUY", -fl.notional, fl.fee, f"{f.symbol} entry")
            tk.transition(S.FILLED, f"px {fl.avg_px} slip {fl.slippage_bps.quantize(D('0.01'))}bps")
            m.trace(tk, "S36", "C5", "fill", "RESULT", f"paper BUY {fl.qty} {f.symbol} @ {fl.avg_px} fee {fl.fee}")
        # settle: S43 marks open positions; S45 reconcile ledger cash vs engine cash
        open_mtm = {s: str((q*last_px[s].bid).quantize(D("0.01"))) for s,(q,_,_) in pos.items()}
        led_cash = START_EQUITY + sum((D(a)-D(fe) for *_,a,fe,_ in [r[3:] for r in self.store.rows("ledger")]), D(0))
        drift = led_cash - cash
        await R["S43"].run(lambda: open_mtm); await R["S45"].run(lambda: drift)
        final = cash + sum(q*last_px[s].bid for s,(q,_,_) in pos.items())
        fees = sum((x.fee for x in fills), D(0))
        rts = [r for r in self.store.rows("trace") if r[3]=="S44"]
        wins = sum(1 for r in rts if not r[7].split(": ")[1].startswith("-"))
        return {"source": "fixtures/binance_replay_sample.jsonl (synthetic sample prices, not real market data)",
                "source_sha256": src.sha256(), "span_days": round((feats[-1].ts-feats[0].ts)/86400, 3),
                "qa": {"input_rows": qa.input_rows, "kept": len(qa.ticks), "duplicates": qa.duplicates, "crossed": qa.crossed,
                       "non_trading": qa.non_trading, "gaps": qa.gaps, "out_of_order": qa.out_of_order},
                "start_equity": str(START_EQUITY), "final_equity_mtm": str(final.quantize(D("0.0001"))),
                "net_pnl_after_costs": str((final-START_EQUITY).quantize(D("0.0001"))), "fees_paid": str(fees.quantize(D("0.0001"))),
                "avg_slippage_bps": str((sum((x.slippage_bps for x in fills), D(0))/len(fills)).quantize(D("0.01"))) if fills else None,
                "fills": len(fills), "round_trips": len(rts), "winning_round_trips": wins, "open_positions_mtm": open_mtm,
                "vetoes": vetoes, "reconciliation_drift": str(drift), "equity_curve": equity_curve,
                "daily_pnl_realized": {k: str(v.quantize(D("0.0001"))) for k,v in daily.items()},
                "fill_log": [{"ts":x.ts,"symbol":x.symbol,"side":x.side,"qty":str(x.qty),"px":str(x.avg_px.quantize(D("0.01"))),
                              "fee":str(x.fee.quantize(D("0.0001"))),"slip_bps":str(x.slippage_bps.quantize(D("0.01")))} for x in fills]}

    async def _synthetic(self):
        R = self.reg
        d1 = await R["S13"].run(run_d1); d2 = await R["S20"].run(run_d2); d3 = await R["S23"].run(run_d3)
        for k in ("S03","S12","S28","S16"): R[k].calls += 0
        return {"D1": d1, "D2": d2, "D3": d3}

    def run_paper_day(self) -> dict:
        t0 = time.perf_counter()
        async def go(): return await self._d4(), await self._synthetic()
        d4, syn = asyncio.run(go())
        rep = self.reg["S47"]; rep.calls += 1
        tickets = list(self.main.tickets.values())
        self.result = {"mode": self.modes.mode.value, "D4": d4, "synthetic_desks": syn,
            "tickets_by_state": {s.value: sum(1 for t in tickets if t.state is s) for s in S},
            "ticket_outcomes": {k: sum(1 for t in tickets if (t.history[-2][1] if t.state is S.AUDITED and len(t.history)>1 else t.state.value)==k) for k in ("SETTLED","REJECTED","VETOED","FILLED","EXPIRED","FAILED")},
            "strategy_variants_tried": [{"regime_slope_threshold":"0.0005","result":"0 lane agreements, 86 tickets rejected (no fills)"},{"regime_slope_threshold":"0.0001","result":"this run"}],
            "escalations": len(self.main.escalations), "trace_rows": len(self.store.rows("trace")),
            "cost": {"llm_tokens": sum(a.llm_tokens for a in self.reg.all()), "llm_cost_usd": "0.00",
                     "compute_wall_s": round(time.perf_counter()-t0, 3),
                     "note": "0 LLM tokens were used, so metered LLM cost is $0. Infra cost of this box is not metered here."},
            "limits_sha256": self.limits.sha256, "kill_engaged": self.kill.engaged}
        return self.result
