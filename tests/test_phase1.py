import sqlite3, pytest, asyncio
from decimal import Decimal as D
from crew.models import *
from crew.models import TicketState as S
from crew.store import SQLiteStore
from crew.risk import Limits, RiskEngine, LimitsTamper
from crew.modes import gate, Mode, Stats, ModeController
from crew import drills
from crew.drills import _oi, _pf, LIMITS

def test_ticket_happy_path_and_illegal():
    t = Ticket("D4","BTC","binance")
    for s in [S.ENRICHED,S.PRICED,S.RESEARCHED,S.RISK_CLEARED,S.APPROVED,S.ORDERED,S.FILLED,S.SETTLED,S.AUDITED]: t.transition(s)
    with pytest.raises(IllegalTransition): t.transition(S.DISCOVERED)
    t2 = Ticket("D4","BTC","binance")
    with pytest.raises(IllegalTransition): t2.transition(S.ORDERED)
    with pytest.raises(IllegalTransition): t2.transition("FILLED")
    t2.transition(S.REJECTED); t2.transition(S.AUDITED)

def test_approval_hmac(monkeypatch):
    a = Approval("x","owner","APPROVE").signed(); assert a.verify()
    forged = Approval("y","owner","APPROVE",a.ts,a.signature); assert not forged.verify()
    monkeypatch.delenv("CREW_APPROVAL_HMAC_KEY"); assert not a.verify()
    with pytest.raises(ApprovalKeyMissing): Approval("x","o","APPROVE").signed()

def test_config_versions():
    c = ConfigStore(); c.commit({"a":1},"o"); c.commit({"a":2,"b":1},"o")
    assert c.diff(1,2) == {"a":(1,2),"b":(None,1)}
    r = c.rollback(1,"o"); assert r.version == 3 and r.data == {"a":1} and len(c.versions) == 3

def test_trace_append_only():
    st = SQLiteStore(); st.append_trace(TraceRow("t","S01","C1","ingest","RESULT","x"))
    for sql in ["UPDATE trace SET content='y'", "DELETE FROM trace"]:
        with pytest.raises(sqlite3.IntegrityError): st.db.execute(sql)
    assert len(st.rows("trace")) == 1
    with pytest.raises(TypeError): st.append_ledger("PAPER","t","fill",1.0,D(0))

def test_risk_fail_closed_and_at_limit():
    e = RiskEngine(Limits(LIMITS))
    assert e.check(_oi(), _pf()).approved
    assert not e.check(None, _pf()).approved
    assert not e.check(_oi(notional=100.0), _pf()).approved
    assert not e.check(_oi(notional=D(200)), _pf()).approved        # 2% exactly = breach
    assert not e.check(_oi(expected_slippage_bps=D(20)), _pf()).approved
    assert not e.check(_oi(liquidity_usd=D(100000)), _pf()).approved
    assert not e.check(_oi(), _pf(open_positions=3)).approved
    assert not e.check(_oi(), _pf(daily_pnl=D(-200))).approved
    assert not e.check(_oi(), _pf(weekly_pnl=D(-500))).approved
    assert not e.check(_oi(), _pf(seconds_since_last_loss=1800)).approved
    assert not e.check(_oi(is_withdrawal=True), _pf()).approved
    assert not e.check(_oi(), _pf(venue_exposure={"binance":D(900)})).approved
    assert not e.check(_oi(), _pf(gross_exposure=D(1900))).approved
    class Boom(type(_pf())): pass
    e2 = RiskEngine(Limits(LIMITS)); e2._check = lambda o,p: (_ for _ in ()).throw(RuntimeError("x"))
    assert not e2.check(_oi(), _pf()).approved
    e3 = RiskEngine(Limits(LIMITS)); import time; e3._check = lambda o,p: time.sleep(0.2)
    assert "timeout" in e3.check(_oi(), _pf(), timeout_s=0.01).reasons[0]
    assert "previous risk check is still running" in e3.check(_oi(), _pf(), timeout_s=0.1).reasons[0]
    time.sleep(0.25)
    e3._check = RiskEngine(Limits(LIMITS))._check
    assert e3.check(_oi(), _pf()).approved
    e4 = RiskEngine(Limits(LIMITS)); e4._check = lambda o,p: None
    assert not e4.check(_oi(), _pf()).approved

def test_limits_immutable():
    L = Limits(LIMITS)
    with pytest.raises(LimitsTamper): L.max_open_positions = 99
    with pytest.raises(LimitsTamper): del L.max_open_positions
    assert L.max_open_positions == 3 and len(L.tamper_log) == 2

def test_mode_default_and_gates(monkeypatch):
    assert ModeController().mode is Mode.PAPER
    good = Stats(D(1),True,45,D(1),D(0),True,45,True)
    assert not gate(Mode.PAPER, Mode.LIVE_APPROVAL, good).allowed
    a = Approval("promote:PAPER->LIVE_APPROVAL","owner","APPROVE").signed()
    g = gate(Mode.PAPER, Mode.LIVE_APPROVAL, good, a); assert not g.allowed and "LIVE_ENABLED=false" in g.reasons
    monkeypatch.setenv("LIVE_ENABLED", "true")
    assert gate(Mode.PAPER, Mode.LIVE_APPROVAL, good, a).allowed
    g = gate(Mode.LIVE_APPROVAL, Mode.LIVE_AUTO, Stats(D(1),True,45,D(1),D(0),True,0,False),
             Approval("promote:LIVE_APPROVAL->LIVE_AUTO","owner","APPROVE").signed())
    assert "needs 30+ supervised live days (have 0)" in g.reasons
    assert "live slippage outside/unknown versus model" in g.reasons
    assert gate(Mode.REPLAY, Mode.PAPER, good).allowed
    assert not gate(Mode.REPLAY, Mode.LIVE_APPROVAL, good).allowed

def test_live_auto_can_pass_only_with_supervised_evidence_and_approval(monkeypatch):
    monkeypatch.setenv("LIVE_ENABLED","true")
    g = gate(Mode.LIVE_APPROVAL, Mode.LIVE_AUTO, Stats(D(1),True,99,D(1),D(0),True,99,True),
             Approval("promote:LIVE_APPROVAL->LIVE_AUTO","owner","APPROVE").signed())
    assert g.allowed, g.reasons

@pytest.mark.parametrize("name", list(drills.ALL))
def test_drill(name): assert drills.ALL[name]()["passed"]
