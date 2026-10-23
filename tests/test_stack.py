import asyncio, pytest, sys
from decimal import Decimal as D
from datetime import datetime, date
from crew.agents import Registry, AgentDisabled, ENABLED
from crew.overseer import MainGrok
from crew.store import SQLiteStore
from crew.connectors import all_connectors, LiveAdapter, LiveDisabled
from crew.desks_synthetic import DESKS, DeskLocked, run_d1, run_d2, run_d3, brier
from crew.modes import Mode
from crew import desk_d5
from crew.desk_d4 import s09_dataqa, s01_tape, Tick, s36_paper_fill, FEE_RATE
from crew.connectors import BinanceReplay

OWN={"Authorization":"Bearer own-t"}; OP={"Authorization":"Bearer op-t"}; VW={"Authorization":"Bearer view-t"}

def test_registry_50_and_disabled_never_run():
    r = Registry(); assert len(r.all()) == 50 and len({a.agent_id for a in r.all()}) == 50
    with pytest.raises(AgentDisabled): asyncio.run(r["S22"].run(lambda: 1))
    assert r["S37"].health()["status"] == "DISABLED_BY_POLICY"

def test_overseer_quorum_and_deadline():
    r = Registry(); m = MainGrok(r, SQLiteStore()); t = m.open_ticket("crypto_signal","BTC","binance")
    import time
    res = asyncio.run(m.fan_out(t, {"S10": lambda: "LONG", "S14": lambda: time.sleep(0.5) or "LONG"}, deadline_s=0.1))
    assert not m.arbitrate(t, res, "LONG") and m.escalations
    res = asyncio.run(m.fan_out(t, {"S10": lambda: "LONG", "S22": lambda: "LONG"}))   # S22 disabled -> only 1 lane
    assert not m.arbitrate(t, res, "LONG")
    res = asyncio.run(m.fan_out(t, {"S10": lambda: "LONG", "S14": lambda: "LONG"}))
    assert m.arbitrate(t, res, "LONG")
    assert any("rationale" in row[7] for row in m.store.rows("trace"))

def test_paper_day_reconciles(paper):
    d = paper.result["D4"]
    assert d["qa"]["kept"] == 8640 and D(d["reconciliation_drift"]) == 0
    assert d["fills"] == 2 * d["round_trips"] + len(d["open_positions_mtm"])
    assert D(d["fees_paid"]) > 0 and paper.result["cost"]["llm_tokens"] == 0
    assert paper.result["mode"] == "PAPER"
    assert all(x["side"] in ("BUY","SELL") for x in d["fill_log"])

def test_paper_fill_costs():
    t = s01_tape(BinanceReplay().path)[0]
    f = s36_paper_fill("x", t, "BUY", D("150"))
    assert f.fee == (f.notional*FEE_RATE).quantize(D("0.00000001")) and f.avg_px >= t.ask

def test_dataqa_drops_dupes_and_crossed():
    t = s01_tape(BinanceReplay().path)[:4]
    bad = Tick(t[0].ts+999, t[0].symbol, D(2), D(1), (), (), D(0), "TRADING")
    q = s09_dataqa(t + [t[0], bad]); assert q.duplicates == 1 and q.crossed == 1

def test_connectors_contract_and_live_disabled():
    for c in all_connectors():
        if isinstance(c, LiveAdapter):
            assert c.health()["status"] == "DISABLED"
            with pytest.raises(LiveDisabled): c.place_order()
        else:
            assert c.health()["status"] == "OK" and c.test()["passed"]

def test_live_adapter_blocked_even_if_live_enabled(monkeypatch):
    monkeypatch.setenv("LIVE_ENABLED", "true")
    with pytest.raises(LiveDisabled): LiveAdapter("x","y").place_order()

def test_synthetic_desks_locked():
    for d in DESKS.values():
        d.set_mode(Mode.REPLAY)
        with pytest.raises(DeskLocked): d.set_mode(Mode.PAPER)
    assert all("SYNTHETIC" in x["label"] for x in run_d1()+run_d2()+run_d3())
    assert [x["verdict"] for x in run_d3()] == ["PASS","DROP","DROP"]
    assert brier(["1","0"],["1","0"]) == 0

# ---- D5 India ----
needs_india = pytest.mark.skipif(not (desk_d5.INDIA_ROOT/'indiatrader').is_dir(), reason='archived /workspace/indiatrader not present (fresh clone/CI)')
@needs_india
def test_d5_gate0_matches_archived_limits():
    risk, *_ = desk_d5._import(); L = risk.LIMITS
    assert (L.RISK_PER_TRADE, L.SINGLE_STOCK, L.DAILY_LOSS, L.WEEKLY_LOSS, L.MAX_DD) == (D("0.01"),D("0.10"),D("0.02"),D("0.03"),D("0.06"))
    assert L.ALLOWED_PRODUCTS == frozenset({"CNC"}) and L.ENTRY_END_MIN == 900

def test_d5_timing_cutoffs():
    IST = desk_d5.IST; f = lambda h,m,s: desk_d5.timing(datetime(2026,10,20,h,m,s,tzinfo=IST))
    assert f(14,59,59)["entries"] and not f(15,0,0)["entries"]
    assert not f(15,19,59)["square_off"] and f(15,20,0)["square_off"]
    assert not f(15,24,59)["disabled"] and f(15,25,0)["disabled"]
    assert desk_d5.timing(datetime(2026,10,20,10,0))["entries"] is False

def test_d5_sebi_gates_block():
    s = desk_d5.OwnerSignals()
    assert not desk_d5.can_leave_replay(sig=s)
    s = desk_d5.parse_owner_signal("ALGO-ID CONFIRMED", s); s = desk_d5.parse_owner_signal("VPS IP WHITELISTED", s)
    s = desk_d5.parse_owner_signal("algo id confirmed", s)
    assert s.algo_id_confirmed and s.static_ip_whitelisted
    full = desk_d5.OwnerSignals(True, True, True, True)
    assert not desk_d5.can_leave_replay(sig=full, strategy_approved=True)   # live_enabled always False here
    r = desk_d5.order_rate_check([0.0 + i*0.1 for i in range(9)]); assert r["flag"]
    assert not desk_d5.order_rate_check([0.0, 5.0])["flag"]

@needs_india
def test_d5_replay_checks_only():
    r = desk_d5.replay(max_days=30, probe_every=10)
    assert r["universe_fail"] == 0 and r["pre_universe_date"].startswith("fail-closed")
    for p in r["probes"]:
        assert p["15:00 CNC"] == "OUTSIDE_WINDOW" and p["10:00 MIS"] == "PRODUCT_NOT_ALLOWED" and p["calendar_entry"] == "CALENDAR_MISSING"
    assert "pnl" not in str(r).lower().replace("no pnl","")

def test_d5_isolated():
    src = open(desk_d5.__file__).read()
    assert "desk_d4" not in src and "desks_synthetic" not in src

@needs_india
def test_d5_does_not_write_into_indiatrader():
    import os, time
    before = {p: os.stat(p).st_mtime for p in __import__("glob").glob("/workspace/indiatrader/**/*", recursive=True) if os.path.isfile(p)}
    desk_d5.replay(max_days=3)
    after = {p: os.stat(p).st_mtime for p in __import__("glob").glob("/workspace/indiatrader/**/*", recursive=True) if os.path.isfile(p)}
    assert before == after

# ---- API ----
def test_api_auth(client):
    assert client.get("/api/summary").status_code == 401
    assert client.get("/api/summary", headers={"Authorization":"Bearer nope"}).status_code == 401
    assert client.get("/api/summary", headers=VW).json()["mode"] == "PAPER"
    assert client.post("/api/kill", json={}, headers=VW).status_code == 403
    assert client.post("/api/approvals", json={"subject":"x","decision":"APPROVE"}, headers=OP).status_code == 403

def test_api_mode_capped(client):
    for m in ("LIVE_APPROVAL","LIVE_AUTO"):
        assert client.post("/api/mode", json={"mode":m}, headers=OWN).status_code == 403
    assert client.post("/api/mode", json={"mode":"PAPER","desk":"D3"}, headers=OWN).status_code == 403
    assert client.post("/api/mode", json={"mode":"PAPER","desk":"D5"}, headers=OWN).status_code == 403
    assert client.get("/api/mode", headers=VW).json()["mode"] == "PAPER"

def test_live_environment_cannot_promote(client, monkeypatch):
    from crew.modes import Stats, gate
    from crew.models import Approval
    monkeypatch.setenv("LIVE_ENABLED", "true")
    good = Stats(D(1), True, 99, D(1), D(0), True, 99, True)
    a = Approval("promote:PAPER->LIVE_APPROVAL", "owner", "APPROVE").signed()
    assert not gate(Mode.PAPER, Mode.LIVE_APPROVAL, good, a).allowed
    assert client.get("/api/summary", headers=VW).json()["live_enabled"].startswith("false")

def test_health_and_bounded_queries(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json()["ready"] is True
    assert client.get("/api/trace?limit=0", headers=VW).json() == []
    assert client.get("/api/trace?limit=2001", headers=VW).status_code == 422
    assert client.get("/api/memory?limit=-1", headers=VW).status_code == 422
    assert client.get("/api/memory?limit=501", headers=VW).status_code == 422

def test_api_limits_not_editable(client):
    assert client.post("/api/configs", json={"data":{"max_position_pct":"0.9"}}, headers=OWN).status_code == 403
    assert client.post("/api/configs", json={"data":{"ui_theme":"neon"}}, headers=OWN).status_code == 200

def test_api_signed_approval_not_sufficient(client):
    r = client.post("/api/approvals", json={"subject":"promote:PAPER->LIVE_APPROVAL","decision":"APPROVE"}, headers=OWN).json()
    assert r["verified"] and not r["gate_result"]["allowed"]

def test_api_pages_and_agents(client):
    for p in ("agents","tickets","trace","pnl","markets","risk","connectors","configs","approvals","reports","research","india","desks","audit"):
        assert client.get(f"/api/{p}", headers=VW).status_code == 200, p
    assert len(client.get("/api/agents", headers=VW).json()) == 50
    assert client.get("/api/pnl", headers=VW).json()["live"] is None
    with client.websocket_connect("/ws/pnl") as ws:
        ws.send_json({"auth": "view-t"}); assert ws.receive_json()["channel"] == "pnl"

def test_auth_header_only_and_ws_first_message(client):
    from starlette.websockets import WebSocketDisconnect
    assert client.get("/api/summary?token=view-t").status_code == 401          # URL tokens rejected
    assert client.get("/api/summary", headers={"Authorization": "view-t"}).status_code == 401   # bare token rejected
    with client.websocket_connect("/ws/pnl?token=view-t") as ws:
        ws.send_json({"hello": 1})
        with pytest.raises(WebSocketDisconnect): ws.receive_json()
    with client.websocket_connect("/ws/unknown") as ws:
        ws.send_json({"auth": "view-t"})
        with pytest.raises(WebSocketDisconnect) as e: ws.receive_json()
        assert e.value.code == 4404

def test_owner_totp_optional(client, monkeypatch):
    import pyotp
    body = {"subject": "note:totp-test", "decision": "REJECT"}
    assert client.post("/api/approvals", headers=OWN, json=body).status_code == 200      # disabled when unset
    sec = pyotp.random_base32(); monkeypatch.setenv("CREW_OWNER_TOTP_SECRET", sec)
    assert client.post("/api/approvals", headers=OWN, json=body).status_code == 401
    assert client.post("/api/approvals", headers={**OWN, "X-TOTP": "000000" if pyotp.TOTP(sec).now() != "000000" else "111111"}, json=body).status_code == 401
    assert client.post("/api/approvals", headers={**OWN, "X-TOTP": pyotp.TOTP(sec).now()}, json=body).status_code == 200
    assert client.get("/api/summary", headers=VW).status_code == 200                      # view unaffected

def test_api_kill_last(client):
    r = client.post("/api/kill", json={"reason":"test"}, headers=OP); assert r.status_code == 200
    s = client.get("/api/summary", headers=VW).json(); assert s["kill"]["engaged"] and "D4" in s["kill"]["desks_halted"]
    assert client.post("/api/kill/reset", headers=VW).status_code == 403
    reset = client.post("/api/kill/reset", headers=OWN)
    assert reset.status_code == 200 and reset.json()["approval_verified"]
    assert not client.get("/api/summary", headers=VW).json()["kill"]["engaged"]
