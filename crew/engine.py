"""Wires everything: overseer, crew agents, risk engine, kill switch, ledger, D4 paper run, D1-D3 replay desks."""
from __future__ import annotations
import asyncio, hashlib, json, time
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path
from .agents import Registry
from .connectors import BinanceReplay, all_connectors
from .desks_synthetic import DESKS, load, d1_price, d1_edge, s19_insider, s20_redflags, s23_forensics, s24_holders, LABEL
from .desk_d4 import s01_tape, s09_dataqa, s10_features, s14_regime, s27_size, s36_paper_fill, day_of, FEE_RATE, book_walk
from .killswitch import KillSwitch
from .models import TicketState as S, RiskEvent, ConfigStore
from .modes import ModeController, Mode
from .overseer import MainGrok
from . import skills as SK
from .risk import utilisation, Limits, LimitsAuditor, RiskEngine, OrderIntent, Portfolio
from .store import SQLiteStore, AppendOnlyStore
from .orderbook import StalenessGuard
from collections import Counter
from .memory import SharedMemory, Fact

ROOT = Path(__file__).resolve().parent.parent
LIMITS = ROOT/"config"/"limits.json"
START_EQUITY = D("10000")

class CrewSystem:
    def __init__(self, db=":memory:", fast=20, slow=60, slope=D("0.0001"), store: AppendOnlyStore | None = None,
                 memory: SharedMemory | None = None):
        self.fast, self.slow, self.slope = fast, slow, D(str(slope))
        self.memory = memory
        self.risk_util = {"checks": 0, "last": None, "peak": {}}
        self.telemetry = {"intents_submitted": 0, "risk_breaches": 0, "rejects": Counter(), "quorum": Counter(), "latency_s": []}
        self.store = store if store is not None else SQLiteStore(db); self.reg = Registry(); self.kill = KillSwitch()
        self.limits = Limits(LIMITS); self.auditor = LimitsAuditor(self.limits, LIMITS)
        self.risk = RiskEngine(self.limits, self.kill, self.auditor)
        self.modes = ModeController(); self.main = MainGrok(self.reg, self.store)
        self.config = ConfigStore(); self.config.commit({"limits_sha256": self.limits.sha256, "start_equity": str(START_EQUITY),
                                                         "fee_rate": str(FEE_RATE), "strategy": f"ema{fast}/{slow} cross + regime quorum (slope>{slope})"}, "system", "boot")
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
        feats = await R["S10"].run(s10_features, list(qa.ticks), self.fast, self.slow)
        tick_by = {(t.symbol, t.ts): t for t in qa.ticks}
        cash, pos, fills, equity_curve = START_EQUITY, {}, [], []
        daily, peak, last_loss_ts, vetoes = defaultdict(D), START_EQUITY, None, []
        modeled_slip = {}; self._ticks = qa.ticks
        prev = {}; last_px = {}
        g = json.loads((ROOT/"config"/"feed_guard.json").read_text())
        self.guard = guard = StalenessGuard(int(g["max_gap_s"]), int(g["max_drift_s"]))
        tel = self.telemetry
        for f in feats:
            t = tick_by[(f.symbol, f.ts)]; last_px[f.symbol] = t
            fresh, why = guard.check(f.symbol, f.ts)   # replay clock; blocks signal evaluation on stale/backwards data
            p0 = prev.get(f.symbol); prev[f.symbol] = f
            if p0 is None: continue
            cross_up = p0.ema_f <= p0.ema_s and f.ema_f > f.ema_s
            cross_dn = p0.ema_f >= p0.ema_s and f.ema_f < f.ema_s
            mtm = cash + sum(q*last_px[s].bid for s,(q,_,_) in pos.items())
            peak = max(peak, mtm)
            if f.ts % 3600 == 0: equity_curve.append((f.ts, str(mtm.quantize(D("0.01")))))
            if not fresh: tel["rejects"][f"stale_data:{why}"] += 1; continue
            if cross_dn and f.symbol in pos:
                q, cost, tid = pos.pop(f.symbol); tk = m.tickets[tid]
                fl = await R["S36"].run(s36_paper_fill, tid, t, "SELL", None, q)
                cash += fl.notional - fl.fee; fills.append(fl)
                self.store.append_ledger(self.modes.mode.value, tid, "SELL", fl.notional, fl.fee, f"{f.symbol} exit on cross down")
                pnl = fl.notional - fl.fee - cost; daily[day_of(f.ts)] += pnl
                if pnl < 0: last_loss_ts = f.ts
                tk.transition(S.SETTLED, f"net pnl {pnl.quantize(D('0.0001'))}"); tk.transition(S.AUDITED)
                await R["S44"].run(m.trace, tk, "S44", "C6", "pnl", "RESULT", f"round trip net of fees+slippage: {pnl.quantize(D('0.0001'))} USDT")
            if not cross_up or f.symbol in pos: continue
            t_sig = time.perf_counter(); n_esc = len(m.escalations)
            tk = m.open_ticket("crypto_signal", f.symbol, "binance")
            tk.transition(S.ENRICHED, "DataQA passed"); tk.transition(S.PRICED, "features computed")
            res = await m.fan_out(tk, {"S10": lambda p0=p0, f=f: "LONG" if (p0.ema_f <= p0.ema_s and f.ema_f > f.ema_s) else "FLAT", "S14": lambda f=f: "LONG" if s14_regime(f, self.slope) == "TREND_UP" else s14_regime(f, self.slope)})
            q_ok = m.arbitrate(tk, res, "LONG")
            tel["quorum"]["met" if q_ok else ("escalated" if len(m.escalations) > n_esc else "disagree")] += 1
            if not q_ok:
                tk.transition(S.REJECTED, "no quorum agreement"); tk.transition(S.AUDITED)
                tel["rejects"]["no_quorum"] += 1; tel["latency_s"].append(time.perf_counter()-t_sig); continue
            tk.transition(S.RESEARCHED, "quorum met")
            mtm = cash + sum(q*last_px[s].bid for s,(q,_,_) in pos.items())
            notional = await R["S27"].run(s27_size, mtm)
            try: q_prev = (notional/t.ask); slip = abs(book_walk(t.asks, q_prev)-t.mid)/t.mid*10000
            except Exception: slip = D(9999)
            gross = sum((q*last_px[s].bid for s,(q,_,_) in pos.items()), D(0))
            wk = sum(daily.values(), D(0))
            tel["intents_submitted"] += 1
            oi = OrderIntent(tk.ticket_id, "binance", notional, slip, t.qv24)
            pf = Portfolio(mtm, gross, {"binance": gross}, len(pos), daily[day_of(f.ts)], wk, peak,
                          None if last_loss_ts is None else f.ts - last_loss_ts)
            dec = self.risk.check(oi, pf)
            u = utilisation(self.limits, oi, pf); ru = self.risk_util; ru["checks"] += 1; ru["last"] = {"ts": f.ts, "ticket_id": tk.ticket_id, "u": u}
            for k, v in u.items():
                if v is not None and (ru["peak"].get(k) is None or v > ru["peak"][k]): ru["peak"][k] = v
            tel["latency_s"].append(time.perf_counter()-t_sig)
            if not dec.approved:
                tel["risk_breaches"] += 1
                for rsn in dec.reasons: tel["rejects"][f"risk:{rsn}"] += 1
                tk.transition(S.VETOED, "; ".join(dec.reasons)); tk.transition(S.AUDITED)
                vetoes.append({"ts": f.ts, "symbol": f.symbol, "reasons": list(dec.reasons)})
                self.store.append_risk(RiskEvent("VETO", tk.ticket_id, "; ".join(dec.reasons)))
                await R["S34"].run(m.trace, tk, "S34", "C4", "risk", "VETO", "; ".join(dec.reasons)); continue
            tk.transition(S.RISK_CLEARED); tk.transition(S.APPROVED, "PAPER mode: no human gate for paper fills")
            if not self.kill.allow_new_order(): tel["rejects"]["kill_switch"] += 1; tk.transition(S.VETOED, "kill switch"); continue
            await R["S35"].run(s35_route, self.modes.mode.value)
            tk.transition(S.ORDERED); modeled_slip[tk.ticket_id] = slip
            fl = await R["S36"].run(s36_paper_fill, tk.ticket_id, t, "BUY", notional)
            cash -= fl.notional + fl.fee; fills.append(fl); pos[f.symbol] = (fl.qty, fl.notional + fl.fee, tk.ticket_id)
            self.store.append_ledger(self.modes.mode.value, tk.ticket_id, "BUY", -fl.notional, fl.fee, f"{f.symbol} entry")
            tk.transition(S.FILLED, f"px {fl.avg_px} slip {fl.slippage_bps.quantize(D('0.01'))}bps")
            m.trace(tk, "S36", "C5", "fill", "RESULT", f"paper BUY {fl.qty} {f.symbol} @ {fl.avg_px} fee {fl.fee}")
        # settle: S43 marks open positions; S45 reconcile ledger cash vs engine cash
        open_mtm = await R["S43"].run(lambda: {s: str((q*last_px[s].bid).quantize(D("0.01"))) for s,(q,_,_) in pos.items()})
        def s45_reconcile():
            led_cash = START_EQUITY + sum((D(a)-D(fe) for *_,a,fe,_ in [r[3:] for r in self.store.rows("ledger")]), D(0))
            return led_cash - cash
        drift = await R["S45"].run(s45_reconcile)
        final = cash + sum(q*last_px[s].bid for s,(q,_,_) in pos.items())
        fees = sum((x.fee for x in fills), D(0))
        rts = [r for r in self.store.rows("trace") if r[3]=="S44"]
        wins = sum(1 for r in rts if not r[7].split(": ")[1].startswith("-"))
        self._fills, self._modeled_slip, self._daily = fills, modeled_slip, daily
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
        mk = await R["S03"].run(lambda: load("d1_prediction_markets.json")["markets"])
        priced = [await R["S12"].run(d1_price, m) for m in mk]
        d1 = [await R["S13"].run(d1_edge, m, p) for m, p in priced]
        for x, (m, p) in zip(d1, priced):   # S28: capped Kelly on the binary (payoff = (1-ask)/ask), replay-only
            ask = D(m["yes_ask"]); x["kelly_capped"] = str(await R["S28"].run(SK.kelly_fraction, p, (1-ask)/ask, D("0.25")))
        fl = await R["S06"].run(lambda: load("d2_filings.json")["filings"])
        d2 = []
        for x in fl:
            cl = await R["S19"].run(s19_insider, x); flags = await R["S20"].run(s20_redflags, x)
            d2.append({"ticker": x["ticker"], "form": x["form"], "red_flags": flags, "insider_cluster_buy": cl, "watch": cl and not flags, "label": LABEL})
        tk = await R["S05"].run(lambda: load("d3_tokens.json")["tokens"])
        d3 = []
        for t in tk:
            res = (await R["S23"].run(s23_forensics, t)) + [await R["S24"].run(s24_holders, t)]
            order = ["min_liquidity","age_hours","deployer_prior_rugs","top10_holders_pct","mint_authority_revoked"]
            res = sorted(res, key=lambda r: order.index(r[0]))
            d3.append({"symbol": t["symbol"], "filters": res, "verdict": "PASS" if all(v for _, v in res) else "DROP", "label": LABEL})
        return {"D1": d1, "D2": d2, "D3": d3}

    async def _post_run(self, d4):
        """Post-run monitors and accounting. They measure and record; none of them is in the trade decision path
        (the RiskEngine alone enforces limits before an order)."""
        R, out = self.reg, {}
        by_sym = defaultdict(list)
        for t in self._ticks: by_sym[t.symbol].append(t.mid)
        out["S11_realized_vol_per_tick"] = {k: str((await R["S11"].run(SK.realized_vol, v)).quantize(D("0.0000001"))) for k, v in by_sym.items()}
        syms = sorted(by_sym)
        def corr(a, b):
            n = min(len(a), len(b)); ra = [a[i]/a[i-1]-1 for i in range(1, n)]; rb = [b[i]/b[i-1]-1 for i in range(1, n)]
            ma, mb = sum(ra, D(0))/len(ra), sum(rb, D(0))/len(rb)
            cov = sum(((x-ma)*(y-mb) for x, y in zip(ra, rb)), D(0)); va = sum(((x-ma)**2 for x in ra), D(0)); vb = sum(((y-mb)**2 for y in rb), D(0))
            return cov/(va.sqrt()*vb.sqrt()) if va and vb else None
        out["S32_return_correlation"] = {f"{a}/{b}": str((await R["S32"].run(corr, by_sym[a], by_sym[b])).quantize(D("0.0001")))
                                         for i, a in enumerate(syms) for b in syms[i+1:]}
        def peak_gross():
            pos, pk = defaultdict(D), D(0)
            for f in self._fills:
                pos[f.symbol] += f.notional if f.side == "BUY" else -pos[f.symbol]; pk = max(pk, sum(pos.values(), D(0)))
            return pk
        L = self.limits._d
        pg = await R["S29"].run(peak_gross)
        out["S29_peak_gross_notional_at_cost"] = str(pg.quantize(D("0.01")))
        out["S30_loss_tracking"] = await R["S30"].run(lambda: {"worst_day_realized": str(min(self._daily.values(), default=D(0)).quantize(D("0.0001"))),
                                                             "week_realized": str(sum(self._daily.values(), D(0)).quantize(D("0.0001")))})
        out["S31_min_qv24_seen"] = str(await R["S31"].run(lambda: min((t.qv24 for t in self._ticks), default=None)))
        out["S33_limits_file_ok"] = await R["S33"].run(self.auditor.check)
        def slip_gap():
            buys = [f for f in self._fills if f.side == "BUY" and f.ticket_id in self._modeled_slip]
            if not buys: return None
            return str((sum((f.slippage_bps - self._modeled_slip[f.ticket_id] for f in buys), D(0))/len(buys)).quantize(D("0.0001")))
        out["S42_mean_realized_minus_modeled_slip_bps"] = await R["S42"].run(slip_gap)
        ind = await R["S44"].run(self.store.net_pnl, self.modes.mode.value)
        out["S44_ledger_cash_flow_check"] = str(ind.quantize(D("0.0001")))
        def model_check():
            cur = self.config.current().data
            return {"version": self.config.current().version, "matches_run": cur.get("limits_sha256") == self.limits.sha256 and cur.get("fee_rate") == str(FEE_RATE)}
        out["S17_model_registry"] = await R["S17"].run(model_check)
        return out

    def run_paper_day(self) -> dict:
        t0 = time.perf_counter()
        async def go(): return await self._d4(), await self._synthetic()
        d4, syn = asyncio.run(go())
        post = asyncio.run(self._post_run(d4))
        tickets = list(self.main.tickets.values())
        self.result = {"mode": self.modes.mode.value, "D4": d4, "synthetic_desks": syn,
            "tickets_by_state": {s.value: sum(1 for t in tickets if t.state is s) for s in S},
            "ticket_outcomes": {k: sum(1 for t in tickets if (t.history[-2][1] if t.state is S.AUDITED and len(t.history)>1 else t.state.value)==k) for k in ("SETTLED","REJECTED","VETOED","FILLED","EXPIRED","FAILED")},
            "strategy_variants_tried": [{"regime_slope_threshold":"0.0005","result":"0 lane agreements, 86 tickets rejected (no fills)"},{"regime_slope_threshold":"0.0001","result":"this run"}],
            "escalations": len(self.main.escalations), "trace_rows": len(self.store.rows("trace")),
            "cost": engine_llm_cost(sum(a.llm_tokens for a in self.reg.all()), round(time.perf_counter()-t0, 3)),
            "run_id": self.store.run_id, "feed_guard": {"max_gap_s": self.guard.max_gap_s, "blocked": dict(self.guard.blocked)}, "limits_sha256": self.limits.sha256, "kill_engaged": self.kill.engaged, "agent_work": post}
        async def tail():
            self.result["cost"] = await self.reg["S48"].run(lambda c=self.result["cost"]: {**c, "agent_calls": sum(a.calls for a in self.reg.all())})
            self.result["brief"] = await self.reg["S26"].run(morning_brief, self.result)
            self.result["honest_summary"] = await self.reg["S47"].run(honest_summary, self.result)
            self.result["archive_sha256"] = await self.reg["S50"].run(lambda: hashlib.sha256(json.dumps(
                {t: self.store.rows(t) for t in ("trace","ledger","risk_events","audit_log")}, default=str).encode()).hexdigest())
        asyncio.run(tail())
        self.result["agents_invoked"] = sorted(a.agent_id for a in self.reg.all() if a.calls)
        self._remember()
        return self.result

    def _remember(self):
        """Deterministic agents record what they measured into the single shared memory (no LLM involved)."""
        if self.memory is None: return
        d4, prov = self.result["D4"], f"paper-run sha256:{self.result['D4']['source_sha256'][:12]}"
        for aid, topic, kind, txt in [
            ("S09", "dataqa", "metric", json.dumps(d4["qa"])),
            ("S44", "pnl", "metric", f"paper net after costs {d4['net_pnl_after_costs']} USDT; fees {d4['fees_paid']}; fills {d4['fills']}"),
            ("S45", "reconciliation", "metric", f"ledger vs engine drift {d4['reconciliation_drift']}"),
            ("S34", "risk", "observation", f"{len(d4['vetoes'])} risk vetoes this run"),
            ("S47", "report", "report", f"outcomes {json.dumps(self.result['ticket_outcomes'])}; sample too small to infer edge"),
            ("S48", "cost", "metric", json.dumps(self.result["cost"]))]:
            self.memory.write(Fact(aid, topic, txt, kind, prov))


def s35_route(mode: str) -> str:
    """S35: only the paper filler is routable in this build; anything else fails closed."""
    if mode not in ("PAPER", "REPLAY"): raise PermissionError(f"no live route in mode {mode}")
    return "S36"

def morning_brief(r: dict) -> str:
    d = r["D4"]
    return (f"D4 paper: net {d['net_pnl_after_costs']} USDT after fees {d['fees_paid']}; {d['fills']} fills, "
            f"{d['winning_round_trips']}/{d['round_trips']} winning round trips; {len(d['vetoes'])} vetoes; drift {d['reconciliation_drift']}. "
            f"Kill switch {'ENGAGED' if r['kill_engaged'] else 'armed'}. Sample is synthetic and too small to infer edge.")

def honest_summary(r: dict) -> dict:
    d = r["D4"]
    return {"net_pnl_after_costs": d["net_pnl_after_costs"], "round_trips": d["round_trips"], "wins": d["winning_round_trips"],
            "claims_edge": False, "data": "synthetic replay sample", "variants_tried": len(r["strategy_variants_tried"])}

def engine_llm_cost(tokens: int, wall_s: float) -> dict:
    """Engine agents never call an LLM, so tokens are 0 and the cost is computed as 0; any non-zero count would have
    no verified price at this layer and is reported as UNKNOWN. Router (JEV) usage is merged in by the API."""
    return {"llm_tokens": tokens, "llm_cost_usd": "0" if tokens == 0 else "UNKNOWN", "compute_wall_s": wall_s,
            "note": "engine agents: 0 LLM calls by design; infra cost of the host is not metered"}
