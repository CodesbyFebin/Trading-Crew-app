"""Drills: each returns a dict of real observed outcomes. Used by tests and scripts/run_drills.py."""
from __future__ import annotations
import asyncio, os, shutil, tempfile
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from .bus import InProcessBus, Backpressure
from .killswitch import KillSwitch
from .models import Event, Ticket, TicketState as S, Approval, now
from .modes import ModeController, Mode, Stats
from .risk import Limits, LimitsAuditor, LimitsTamper, RiskEngine, OrderIntent, Portfolio

LIMITS = Path(__file__).resolve().parent.parent / "config" / "limits.json"
def _pf(**k):
    base = dict(equity=D(10000), gross_exposure=D(0), venue_exposure={}, open_positions=0, daily_pnl=D(0),
                weekly_pnl=D(0), peak_equity=D(10000), seconds_since_last_loss=None)
    base.update(k); return Portfolio(**base)
def _oi(**k):
    base = dict(ticket_id="t", venue="binance", notional=D(100), expected_slippage_bps=D(5), liquidity_usd=D(1000000))
    base.update(k); return OrderIntent(**base)

def kill_switch_drill():
    ks = KillSwitch(); eng = RiskEngine(Limits(LIMITS), ks)
    ts = [Ticket("D4","BTCUSDT","binance") for _ in range(3)]
    ts[1].transition(S.ENRICHED); [ts[2].transition(x) for x in (S.ENRICHED,S.PRICED,S.RESEARCHED,S.RISK_CLEARED,S.APPROVED,S.ORDERED)]
    before = eng.check(_oi(), _pf()).approved
    ks.engage("drill", ["D1","D2","D3","D4"], ts)
    after = eng.check(_oi(), _pf())
    return {"approved_before_kill": before, "approved_after_kill": after.approved, "after_reasons": list(after.reasons),
            "desks_halted": sorted(ks.desks_halted), "ticket_states": [t.state.value for t in ts],
            "all_flagged_killed": all("KILLED" in t.flags for t in ts), "allow_new_order": ks.allow_new_order(),
            "reset_without_signed_approval": ks.reset(None),
            "passed": before and not after.approved and not ks.allow_new_order() and all(not t.is_open for t in ts)}

def drawdown_halt_drill():
    eng = RiskEngine(Limits(LIMITS))
    ok = eng.check(_oi(), _pf(equity=D(9500), peak_equity=D(10000))).approved
    at = eng.check(_oi(), _pf(equity=D(9000), peak_equity=D(10000)))  # exactly 10% = breach
    sticky = eng.check(_oi(), _pf(equity=D(10000), peak_equity=D(10000)))
    return {"dd_5pct_approved": ok, "dd_10pct_at_limit_approved": at.approved, "reasons": list(at.reasons),
            "halt_sticky_after_recovery": not sticky.approved, "passed": ok and not at.approved and not sticky.approved}

def auto_demotion_drill():
    os.environ.setdefault("CREW_APPROVAL_HMAC_KEY", "drill-only-key")
    mc = ModeController(); mc.mode = Mode.LIVE_APPROVAL   # forced start state for drill only
    m1 = mc.on_breach("daily loss breach").value
    m2 = mc.on_breach("reconciliation drift").value
    m3 = mc.on_breach("again").value
    good = Stats(D(1),True,45,D("0.5"),D(0),True)
    unsigned = mc.promote(Mode.PAPER, good)
    mc.mode = Mode.PAPER
    to_live = mc.promote(Mode.LIVE_APPROVAL, good, Approval("promote:PAPER->LIVE_APPROVAL","owner","APPROVE").signed())
    mc.mode = Mode.LIVE_APPROVAL
    to_auto = mc.promote(Mode.LIVE_AUTO, good, Approval("promote:LIVE_APPROVAL->LIVE_AUTO","owner","APPROVE").signed())
    return {"demotions": ["LIVE_APPROVAL", m1, m2, m3], "promote_replay_to_paper": unsigned.allowed,
            "paper_to_live_approval_allowed": to_live.allowed, "paper_to_live_reasons": list(to_live.reasons),
            "live_auto_allowed": to_auto.allowed, "live_auto_reasons": list(to_auto.reasons),
            "passed": [m1,m2,m3]==["PAPER","REPLAY","REPLAY"] and not to_live.allowed and not to_auto.allowed}

def limits_tamper_drill():
    d = Path(tempfile.mkdtemp()); p = d/"limits.json"; shutil.copy(LIMITS, p)
    L = Limits(p); aud = LimitsAuditor(L, p); eng = RiskEngine(L, auditor=aud)
    raised = False
    try: L.max_position_pct = D("0.5")
    except LimitsTamper: raised = True
    before = eng.check(_oi(), _pf()).approved
    p.write_text(p.read_text().replace('"0.02"','"0.90"',1))
    after = eng.check(_oi(), _pf())
    return {"runtime_set_raised": raised, "value_unchanged": str(L.max_position_pct), "approved_before_file_edit": before,
            "approved_after_file_edit": after.approved, "reasons": list(after.reasons),
            "tamper_log": [e.kind for e in L.tamper_log], "passed": raised and before and not after.approved}

def bus_chaos_drill():
    async def go():
        bus = InProcessBus(max_depth=5, max_attempts=2, max_age_s=30)
        ev = Event("S01","tick",{"p":"1"},"k1")
        r = [await bus.publish("t", ev), await bus.publish("t", Event("S01","tick",{"p":"1"},"k1"))]
        stale = Event("S01","tick",{},"k-old", ts=now()-timedelta(seconds=120)); await bus.publish("t", stale)
        # 429 path: consumer nacks, retry once, then dead-letter
        l = await bus.lease("t","c",5); await bus.nack("t", l, "429")
        l = await bus.lease("t","c",5); await bus.nack("t", l, "429")
        nothing = await bus.lease("t","c",5)
        bp = 0
        for i in range(10):
            try: await bus.publish("bp", Event("S01","x",{},f"bp{i}"))
            except Backpressure: bp += 1
        return {"publish_results": r, "stats": bus.stats, "dlq_reasons": [x[2] for x in bus.dlq],
                "lease_after_dlq": nothing is None, "backpressure_rejections": bp,
                "passed": r==[True,False] and sorted(x[2] for x in bus.dlq)==["429","stale"] and bp==5}
    return asyncio.run(go())

ALL = {"kill_switch": kill_switch_drill, "drawdown_halt": drawdown_halt_drill, "auto_demotion": auto_demotion_drill,
       "limits_tamper": limits_tamper_drill, "bus_chaos": bus_chaos_drill}
def run_all(): return {k: f() for k, f in ALL.items()}
