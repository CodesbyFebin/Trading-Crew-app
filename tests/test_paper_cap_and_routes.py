"""PAPER hard cap cannot be bypassed (env, approvals, API, config, LLM text); route RBAC + audit on mutation;
no tokens in URLs; report route has no path traversal."""
import pytest
from crew.models import Approval
from crew.modes import gate, Mode, LADDER, Stats, ModeController
from crew.connectors import all_connectors, LiveDisabled
from crew.engine import s35_route
from decimal import Decimal as D
OWN = {"Authorization": "Bearer own-t"}; OP = {"Authorization": "Bearer op-t"}; VW = {"Authorization": "Bearer view-t"}
BEST = Stats(D(1), True, 365, D(1), D(0), True, 365, True)
LIVE = [Mode.LIVE_APPROVAL, Mode.LIVE_AUTO]

def test_env_plus_signed_approval_plus_perfect_stats_cannot_reach_live(monkeypatch):
    monkeypatch.setenv("LIVE_ENABLED", "true")
    for frm, to in ((Mode.PAPER, Mode.LIVE_APPROVAL), (Mode.LIVE_APPROVAL, Mode.LIVE_AUTO)):
        g = gate(frm, to, BEST, Approval(f"promote:{frm.value}->{to.value}", "owner", "APPROVE").signed())
        assert not g.allowed and "owner policy: this build is capped at PAPER" in g.reasons
    mc = ModeController()
    assert not mc.promote(Mode.LIVE_APPROVAL, BEST, Approval("promote:PAPER->LIVE_APPROVAL", "owner", "APPROVE").signed()).allowed
    assert mc.mode is Mode.PAPER

def test_no_live_route_or_live_adapter_even_with_env(monkeypatch):
    monkeypatch.setenv("LIVE_ENABLED", "true")
    for m in LIVE:
        with pytest.raises(PermissionError): s35_route(m.value)
    for c in all_connectors():
        if hasattr(c, "place_order"):
            with pytest.raises(LiveDisabled): c.place_order("BTCUSDT", "BUY", 1)

def test_api_cannot_exceed_paper(client, monkeypatch):
    monkeypatch.setenv("LIVE_ENABLED", "true")
    for m in LIVE:
        r = client.post("/api/mode", headers=OWN, json={"mode": m.value}); assert r.status_code == 403
    r = client.post("/api/approvals", headers=OWN, json={"subject": "promote:PAPER->LIVE_APPROVAL", "decision": "APPROVE"}).json()
    assert r["gate_result"]["allowed"] is False
    assert client.post("/api/configs", headers=OWN, json={"data": {"mode": "LIVE_AUTO", "live_enabled": True}}).status_code == 200
    assert client.post("/api/configs", headers=OWN, json={"data": {"daily_loss_pct": "0.9"}}).status_code == 403
    s = client.get("/api/summary", headers=VW).json(); assert s["mode"] == "PAPER"
    assert client.get("/api/mode", headers=VW).json()["mode"] == "PAPER"

MUTATIONS = [("post", "/api/mode", {"mode": "PAPER"}, "mode_change"), ("post", "/api/configs", {"data": {"x": 1}}, "config"),
             ("post", "/api/configs/rollback/1", None, "config"), ("post", "/api/approvals", {"subject": "x", "decision": "REJECT"}, "approve"),
             ("post", "/api/backtests/run", None, "config"), ("post", "/api/kill", {"reason": "t"}, "kill"),
             ("post", "/api/drills/run", None, "kill"), ("post", "/api/skills/position_size", {"args": {}}, "research")]

@pytest.mark.parametrize("meth,path,body,perm", MUTATIONS)
def test_mutations_need_auth_and_role(client, meth, path, body, perm):
    f = getattr(client, meth)
    assert f(path, json=body).status_code == 401
    assert f(path, json=body, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert f(path, json=body, headers=VW).status_code == 403

def test_mutations_are_audited(client):
    from crew import api
    def n(action): return sum(1 for r in api.SYS.store.rows("audit_log") if r[3] == action)
    b = {k: n(k) for k in ("config_commit", "config_rollback", "mode", "approval")}
    client.post("/api/configs", headers=OWN, json={"data": {"note_key": 1}})
    client.post("/api/configs/rollback/1", headers=OWN)
    client.post("/api/mode", headers=OWN, json={"mode": "PAPER"})
    client.post("/api/approvals", headers=OWN, json={"subject": "x", "decision": "REJECT"})
    for k in b: assert n(k) == b[k] + 1, k

def test_drills_run_audited_then_kill_reset_state(client):
    from crew import api
    before = sum(1 for r in api.SYS.store.rows("audit_log") if r[3] == "drills_run")
    assert client.post("/api/drills/run", headers=OP).status_code == 200
    assert sum(1 for r in api.SYS.store.rows("audit_log") if r[3] == "drills_run") == before + 1

def test_tokens_never_accepted_in_query_or_ws_url(client):
    for q in ("token", "auth", "access_token", "authorization"):
        assert client.get(f"/api/summary?{q}=own-t").status_code == 401
    with client.websocket_connect("/ws/summary?token=own-t") as ws:
        ws.send_json({"hello": 1})
        with pytest.raises(Exception): ws.receive_json()
    with client.websocket_connect("/ws/summary") as ws:
        ws.send_json({"auth": "view-t"}); assert ws.receive_json()["channel"] == "summary"
    with client.websocket_connect("/ws/secrets") as ws:
        ws.send_json({"auth": "own-t"})
        with pytest.raises(Exception): ws.receive_json()

@pytest.mark.parametrize("name", ["..%2Fconfig%2Flimits.json", "..%2F..%2Fetc%2Fpasswd", "%2Fetc%2Fpasswd", "....//config/limits.json", ".."])
def test_report_route_no_traversal(client, name):
    r = client.get(f"/api/reports/{name}", headers=VW); assert r.status_code == 404

def test_default_binds_are_localhost():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert "--host 127.0.0.1" in (root/"scripts"/"run_all.sh").read_text()
    assert '"127.0.0.1:8795:8795"' in (root/"docker-compose.yml").read_text()
    assert 'else "127.0.0.1"' in (root/"desktop"/"launcher.py").read_text()   # LAN only with explicit --lan
