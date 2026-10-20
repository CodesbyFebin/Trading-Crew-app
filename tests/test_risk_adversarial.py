"""Finding 4: malformed / adversarial risk inputs and engine faults never approve."""
import dataclasses, time
from decimal import Decimal as D
from pathlib import Path
import pytest
from crew.killswitch import KillSwitch
from crew.risk import Decision, Limits, LimitsTamper, OrderIntent, Portfolio, RiskEngine
from types import MappingProxyType

ROOT = Path(__file__).resolve().parents[1]
def L(): return Limits(ROOT/"config"/"limits.json")
def oi(**k): return dataclasses.replace(OrderIntent("t", "binance", D("100"), D("1"), D("1500000000")), **k)
def pf(**k): return dataclasses.replace(Portfolio(D("10000"), D("0"), {"binance": D("0")}, 0, D("0"), D("0"), D("10000"), None, D("10000")), **k)

def test_baseline_approves(): assert RiskEngine(L()).check(oi(), pf()).approved

BAD_O = [dict(notional=D("NaN")), dict(notional=D("Infinity")), dict(notional=D("-5")), dict(notional=100.0),
         dict(expected_slippage_bps=D("sNaN")), dict(expected_slippage_bps=D("-1")), dict(liquidity_usd=D("-Infinity")),
         dict(venue=""), dict(ticket_id=None), dict(is_withdrawal="no")]
BAD_P = [dict(equity=D("NaN")), dict(equity=D("Infinity")), dict(gross_exposure=D("-1")), dict(daily_pnl=D("NaN")),
         dict(weekly_pnl=D("-Infinity")), dict(peak_equity=D("-1")), dict(open_positions=-1), dict(open_positions=True),
         dict(open_positions=1.5), dict(venue_exposure={"binance": D("-1")}), dict(venue_exposure={"binance": D("NaN")}),
         dict(venue_exposure={"binance": D("50")}), dict(venue_exposure=[]), dict(seconds_since_last_loss=-3),
         dict(day_start_equity=D("0")), dict(day_start_equity=D("NaN"))]

@pytest.mark.parametrize("k", BAD_O)
def test_bad_intent_rejected_with_reason(k):
    d = RiskEngine(L()).check(oi(**k), pf()); assert not d.approved and any(r.startswith("fail-closed") for r in d.reasons)

@pytest.mark.parametrize("k", BAD_P)
def test_bad_portfolio_rejected_with_reason(k):
    d = RiskEngine(L()).check(oi(), pf(**k)); assert not d.approved and any(r.startswith("fail-closed") for r in d.reasons)

def test_wrong_types_rejected():
    assert not RiskEngine(L()).check(object(), pf()).approved
    assert not RiskEngine(L()).check(oi(), {"equity": 1}).approved

def test_at_limit_exposure_and_positions_are_breaches():
    lim = L()
    assert not RiskEngine(lim).check(oi(notional=lim.max_position_pct*D("10000")), pf()).approved
    assert not RiskEngine(lim).check(oi(), pf(open_positions=lim.max_open_positions)).approved
    assert not RiskEngine(lim).check(oi(), pf(gross_exposure=D("1900"), venue_exposure={"binance": D("900")})).approved

def test_timeout_and_worker_errors_fail_closed(monkeypatch):
    re = RiskEngine(L())
    monkeypatch.setattr(re, "_check", lambda o, p: (time.sleep(0.3), Decision(True, ()))[1])
    d = re.check(oi(), pf(), timeout_s=0.05); assert not d.approved and "timeout" in d.reasons[0]
    d2 = re.check(oi(), pf()); assert not d2.approved           # previous check still running -> closed
    time.sleep(0.4)
    def boom(o, p): raise RuntimeError("worker crashed")
    monkeypatch.setattr(re, "_check", boom); assert not re.check(oi(), pf()).approved
    for bad in (None, "APPROVED", Decision(True, ("x",)), Decision(1, ()), Decision(True, ["a"])):
        monkeypatch.setattr(re, "_check", lambda o, p, b=bad: b); assert not re.check(oi(), pf()).approved, bad
    assert not re.check(oi(), pf(), timeout_s=0).approved

def test_kill_engaged_during_check_never_approves(monkeypatch):
    ks = KillSwitch(); re = RiskEngine(L(), ks)
    def slow(o, p): ks.engage("race", ["D4"], []); return Decision(True, ())
    monkeypatch.setattr(re, "_check", slow)
    d = re.check(oi(), pf()); assert not d.approved and "panic kill engaged" in d.reasons

def test_limits_immutable_and_in_memory_tamper_detected():
    lim = L(); re = RiskEngine(lim)
    with pytest.raises(LimitsTamper): lim.daily_loss_pct = D("1")
    with pytest.raises(LimitsTamper): del lim.daily_loss_pct
    with pytest.raises(TypeError): lim._d["daily_loss_pct"] = D("1")
    assert lim.intact() and re.check(oi(), pf()).approved
    d = dict(lim._d); d["max_position_pct"] = D("0.9")
    object.__setattr__(lim, "_d", MappingProxyType(d))          # bypass of the read-only guard
    dec = re.check(oi(), pf()); assert not dec.approved and "limits tampered in memory" in dec.reasons
    assert any(e.kind == "LIMITS_TAMPER" for e in lim.tamper_log)
