"""Finding 1 (HIGH): daily loss must include unrealized (mark-to-market) losses of open positions.
The crash scenario below edits only test copies of the synthetic fixture and the limits file."""
import dataclasses, json, shutil
from decimal import Decimal as D
from pathlib import Path
import pytest
from crew import engine as engine_mod
from crew.desk_d4 import s01_tape, day_of
from crew.models import Approval
from crew.risk import DAILY_LOSS_REASON, Limits, daily_loss_breached, OrderIntent, Portfolio, RiskEngine
from crew.killswitch import KillSwitch
from crew.store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
BASE = engine_mod.CrewSystem(store=SQLiteStore(":memory:")).run_paper_day()["D4"]
FIRST_BUY = next(f for f in BASE["fill_log"] if f["side"] == "BUY")

def _scale(t, k):
    return dataclasses.replace(t, bid=t.bid*k, ask=t.ask*k, bids=tuple((p*k, q) for p, q in t.bids), asks=tuple((p*k, q) for p, q in t.asks))

def _crash_system(monkeypatch, tmp_path, k=D("0.90"), daily="0.0005"):
    lim = json.loads((ROOT/"config"/"limits.json").read_text()); lim["daily_loss_pct"] = daily
    p = tmp_path/"limits.json"; p.write_text(json.dumps(lim)); monkeypatch.setattr(engine_mod, "LIMITS", p)
    t0 = FIRST_BUY["ts"]
    def tape(path):   # a sustained 10% drop of the held symbol from 2 minutes after the first entry
        return [_scale(t, k) if (t.symbol == FIRST_BUY["symbol"] and t.ts >= t0 + 120) else t for t in s01_tape(path)]
    monkeypatch.setattr(engine_mod, "s01_tape", tape)
    sysm = engine_mod.CrewSystem(store=SQLiteStore(":memory:")); snap = {}
    orig = sysm.engage_kill
    def eng(reason, actor):
        orig(reason, actor)
        snap["ledger"] = len(sysm.store.rows("ledger")); snap["day"] = day_of(t0)
    sysm.engage_kill = eng
    return sysm, sysm.run_paper_day(), snap

def test_open_position_breach_engages_kill_without_close(monkeypatch, tmp_path):
    sysm, r, snap = _crash_system(monkeypatch, tmp_path)
    assert sysm.kill.engaged and sysm.kill.reason == DAILY_LOSS_REASON
    led = sysm.store.rows("ledger")
    assert [x[4] for x in led] == ["BUY"]                 # entry only: the losing position was never closed
    assert len(led) == snap["ledger"]                      # no ledger fill after the kill
    assert r["D4"]["open_positions_mtm"]                   # still open, marked to bid
    assert r["D4"]["daily_pnl_realized"] == {}               # nothing realized: realized-only check saw 0
    ev = [x for x in sysm.store.rows("risk_events") if x[2] == "DAILY_LOSS_MTM"]
    assert len(ev) == 1 and "start-of-day" in ev[0][4]
    audits = [x for x in sysm.store.rows("audit_log") if x[3] == "kill"]
    assert len(audits) == 1 and audits[0][2] == "risk-engine:auto"
    assert r["D4"]["reconciliation_drift"] in ("0", "0E-8", "0.00000000") and D(r["D4"]["reconciliation_drift"]) == 0

def test_realized_only_would_have_missed_it(monkeypatch, tmp_path):
    """Same crash with the open-position monitor's inputs: realized daily PnL alone is not a breach."""
    sysm, r, _ = _crash_system(monkeypatch, tmp_path)
    L = sysm.limits; mtm = D(r["D4"]["final_equity_mtm"])
    realized = sum((D(v) for v in r["D4"]["daily_pnl_realized"].values()), D(0))
    assert not daily_loss_breached(L, realized, mtm, engine_mod.START_EQUITY)
    assert daily_loss_breached(L, mtm - engine_mod.START_EQUITY, mtm, engine_mod.START_EQUITY)

def test_kill_persists_across_utc_rollover_until_signed_reset(monkeypatch, tmp_path):
    sysm, r, snap = _crash_system(monkeypatch, tmp_path)
    days = sorted(r["D4"]["daily_pnl_mtm"]); assert len(days) >= 2 and days.index(snap["day"]) < len(days) - 1
    assert sysm.kill.engaged and r["kill_engaged"]         # later UTC days did not clear it
    assert len(sysm.store.rows("ledger")) == snap["ledger"]
    assert not sysm.kill.reset(Approval("kill:reset", "owner", "APPROVE"))
    assert sysm.kill.reset(Approval("kill:reset", "owner", "APPROVE").signed())

def test_small_moves_do_not_trigger(monkeypatch, tmp_path):
    sysm, r, _ = _crash_system(monkeypatch, tmp_path, k=D("0.9999"))
    assert not sysm.kill.engaged and r["D4"]["fills"] > 0

@pytest.mark.parametrize("loss,expect", [("200", True), ("199.9999", False), ("200.0001", True)])
def test_exact_at_limit_is_breach(loss, expect):
    L = Limits(ROOT/"config"/"limits.json")              # daily_loss_pct 0.02 of 10000 = 200
    assert daily_loss_breached(L, -D(loss), D("10000"), D("10000")) is expect
    re = RiskEngine(L, KillSwitch())
    pf = Portfolio(D("10000"), D(0), {}, 0, -D(loss), D(0), D("10000"), None, D("10000"))
    dec = re.check(OrderIntent("t", "binance", D("100"), D("1"), D("1500000000")), pf)
    assert (DAILY_LOSS_REASON in dec.reasons) is expect

def test_base_is_smaller_of_start_and_current_equity():
    L = Limits(ROOT/"config"/"limits.json")
    assert daily_loss_breached(L, -D("190"), D("9500"), D("10000"))      # 2% of 9500 = 190
    assert not daily_loss_breached(L, -D("189"), D("9500"), D("10000"))

def test_track1_reference_unchanged():
    assert (BASE["net_pnl_after_costs"], BASE["fees_paid"], BASE["fills"], BASE["round_trips"]) == ("-3.6518", "3.5936", 24, 12)
    assert D(BASE["reconciliation_drift"]) == 0 and BASE["day_boundary"].startswith("UTC")
