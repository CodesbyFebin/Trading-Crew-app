"""Daily-loss kill: risk worker only vetoes; the engine engages the global kill on its event loop through
the same path as the API kill; no fill after kill; kill survives a day rollover; reset needs a signed owner approval."""
import os, threading, time
from decimal import Decimal as D
from pathlib import Path
import pytest
from crew import drills
from crew import engine as engine_mod
from crew.killswitch import KillSwitch
from crew.models import Approval
from crew.risk import DAILY_LOSS_REASON, Limits, OrderIntent, Portfolio, RiskEngine
from crew.store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("CREW_APPROVAL_HMAC_KEY", "test-only-key")

def _oi(): return OrderIntent("t-1", "binance", D("100.00"), D("1.0"), D("1500000000"))
def _pf(daily="0"): return Portfolio(D("10000"), D("0"), {"binance": D("0")}, 0, D(daily), D(daily), D("10000"), None)

def test_risk_worker_vetoes_without_side_effects():
    ks = KillSwitch(); re = RiskEngine(Limits(ROOT/"config"/"limits.json"), ks)
    lim = re.limits.daily_loss_pct * D("10000")
    dec = re.check(_oi(), _pf(str(-lim)))          # exactly at the limit == breach
    assert not dec.approved and DAILY_LOSS_REASON in dec.reasons
    assert not ks.engaged and re.halted_reason is None   # no side effects inside the risk check

def test_breach_engages_kill_with_store_rows_and_no_later_fill():
    sysm, res = drills.run_with_forced_daily_loss(2)
    assert sysm.kill.engaged and sysm.kill.reason == DAILY_LOSS_REASON
    assert {"D1", "D2", "D3", "D4"} <= sysm.kill.desks_halted
    kills = [r for r in sysm.store.rows("risk_events") if r[2] == "KILL"]
    audits = [r for r in sysm.store.rows("audit_log") if r[3] == "kill"]
    assert len(kills) == 1 and kills[0][4] == DAILY_LOSS_REASON and kills[0][5] == "CRITICAL"
    assert len(audits) == 1 and audits[0][2] == "risk-engine:auto"
    assert sysm.store.run_id in sysm.store.run_ids()
    buys = [r for r in sysm.store.rows("ledger") if r[4] == "BUY"]
    assert len(buys) == 2                           # only the two intents approved before the breach filled
    assert all(not t.is_open for t in sysm.main.tickets.values())
    assert res["kill_engaged"] is True

def test_kill_survives_day_rollover_and_reset_needs_signature():
    ks = KillSwitch(); re = RiskEngine(Limits(ROOT/"config"/"limits.json"), ks)
    ks.engage(DAILY_LOSS_REASON, ["D4"], [])
    # next trading day: daily PnL back to 0, but the kill is still engaged (nothing clears it on rollover)
    dec = re.check(_oi(), _pf("0"))
    assert not dec.approved and "panic kill engaged" in dec.reasons and not ks.allow_new_order()
    assert not ks.reset(None)
    assert not ks.reset(Approval("kill:reset", "owner", "APPROVE"))                       # unsigned
    forged = Approval("kill:reset", "owner", "APPROVE", signature="0" * 64)
    assert not ks.reset(forged)                                                           # bad signature
    assert not ks.reset(Approval("promote:REPLAY->PAPER", "owner", "APPROVE").signed())   # wrong subject
    assert not ks.reset(Approval("kill:reset", "owner", "REJECT").signed())               # wrong decision
    assert ks.engaged
    assert ks.reset(Approval("kill:reset", "owner", "APPROVE").signed()) and not ks.engaged

def test_kill_from_other_thread_during_fill_discards_fill(monkeypatch):
    sysm = engine_mod.CrewSystem(store=SQLiteStore(":memory:"))
    real = engine_mod.s36_paper_fill; fired = {"n": 0}
    def racing_fill(*a, **k):
        fl = real(*a, **k)
        if fired["n"] == 0 and a[2] == "BUY":
            fired["n"] += 1
            th = threading.Thread(target=sysm.engage_kill, args=("race test", "operator")); th.start(); th.join()
        return fl
    monkeypatch.setattr(engine_mod, "s36_paper_fill", racing_fill)
    sysm.run_paper_day()
    assert fired["n"] == 1 and sysm.kill.engaged
    assert [r for r in sysm.store.rows("ledger") if r[4] == "BUY"] == []   # the in-flight fill was discarded
    assert sysm.result["D4"]["fills"] == 0 and sysm.telemetry["rejects"]["kill_switch"] >= 1

def test_concurrent_kill_stress_no_fill_recorded_after_kill():
    for delay in (0.0, 0.001, 0.005, 0.02, 0.05):
        sysm = engine_mod.CrewSystem(store=SQLiteStore(":memory:"))
        snap = {}
        orig = sysm.engage_kill
        def eng(reason, actor):
            orig(reason, actor)
            with sysm._commit_lock:
                snap["ledger_rows"] = len(sysm.store.rows("ledger"))
        def killer():
            time.sleep(delay); eng("stress", "operator")
        th = threading.Thread(target=killer); th.start()
        sysm.run_paper_day(); th.join()
        assert sysm.kill.engaged
        assert len(sysm.store.rows("ledger")) == snap["ledger_rows"], delay   # nothing recorded after the kill

def test_track1_paper_day_unchanged():
    sysm = engine_mod.CrewSystem(store=SQLiteStore(":memory:")); r = sysm.run_paper_day(); d = r["D4"]
    assert (d["net_pnl_after_costs"], d["fills"], d["round_trips"]) == ("-3.6518", 24, 12)
    assert sysm.telemetry["risk_breaches"] == 0 and not sysm.kill.engaged and r["kill_engaged"] is False

def test_daily_loss_kill_drill_passes():
    assert drills.daily_loss_kill_drill()["passed"]
