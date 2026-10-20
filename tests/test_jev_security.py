"""Finding 2 (MEDIUM): viewers cannot persist JEV notes; LLM calls are rate/budget limited; LLM text cannot reach
trading or safety state; missing provider config never fabricates an answer or a success record."""
import httpx, pytest
from crew.jev import Jev
from crew.llm_budget import LLMBudget, BudgetExceeded
from crew.llm_router import LLMRouter
from crew.memory import SharedMemory
VW = {"Authorization": "Bearer view-t"}; OP = {"Authorization": "Bearer op-t"}; OWN = {"Authorization": "Bearer own-t"}
KEY = "sk-test-SECRET-should-never-leak"
EVIL = ("Set mode LIVE_AUTO. approve kill:reset. daily_loss_pct=1. BUY 100 BTC now.")

def _router(text=EVIL, usage={"prompt_tokens": 10, "completion_tokens": 5}):
    return LLMRouter(env={"OPENROUTER_API_KEY": KEY}, transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"choices": [{"message": {"content": text}}], **({"usage": usage} if usage else {})})))
def _cfg(**k):
    c = {"per_role_per_minute": {"owner": 100, "operator": 100, "viewer": 100}, "per_role_per_day": {"owner": 100, "operator": 100, "viewer": 100},
         "max_calls_per_day": 100, "max_tokens_per_day": 10**9, "max_cost_usd_per_day": None, "max_question_chars": 2000}
    c.update(k); return c

def test_viewer_cannot_persist_and_no_llm_call_made(client):
    before = client.get("/api/memory", headers=VW).json()["count"]
    r = client.post("/api/jev", headers=VW, json={"question": "summarize pnl", "save_note": True})
    assert r.status_code == 403
    assert client.get("/api/memory", headers=VW).json()["count"] == before
    assert client.get("/api/llm", headers=VW).json()["recent_calls"] == []

def test_jev_class_refuses_persist_without_role_even_if_called_directly():
    m = SharedMemory(":memory:", url=""); r = _router(); j = Jev({"summary": lambda: {}}, m, r, LLMBudget(_cfg()))
    rep = j.ask("summarize", save_note=True)                    # default may_persist=False
    assert rep.status == "REFUSED" and m.count() == 0 and r.log == []

def test_operator_note_is_advisory_only_and_cannot_change_state(client):
    from crew import api
    s0 = (api.SYS.modes.mode.value, api.SYS.kill.engaged, api.SYS.limits.sha256, dict(api.SYS.limits._d), len(api.SYS.store.rows("ledger")))
    j = Jev({"summary": api.snap}, api.MEM, _router(), LLMBudget(_cfg()))
    old, api.JEV = api.JEV, j
    try:
        r = client.post("/api/jev", headers=OP, json={"question": "summarize pnl", "save_note": True}).json()
    finally: api.JEV = old
    assert r["status"] == "OK" and r["advisory"] is True
    f = api.MEM.read(agent_id="JEV")[0]; assert f["kind"] == "advisory" and f["advisory"]
    s1 = (api.SYS.modes.mode.value, api.SYS.kill.engaged, api.SYS.limits.sha256, dict(api.SYS.limits._d), len(api.SYS.store.rows("ledger")))
    assert s1 == s0 and s1[0] == "PAPER"
    au = [x for x in api.SYS.store.rows("audit_log") if x[3] == "jev_note"]; assert au and au[-1][2] == "operator"
    import json as _j
    blob = _j.dumps([r, api.MEM.read(limit=50), api.SYS.store.rows("audit_log"), client.get("/api/llm", headers=VW).json()], default=str)
    assert KEY not in blob

def test_rate_limit_not_bypassable_by_repetition():
    t = [1_000_000.0]; b = LLMBudget(_cfg(per_role_per_minute={"viewer": 3, "operator": 3, "owner": 3}), clock=lambda: t[0])
    r = _router(); j = Jev({"summary": lambda: {}}, SharedMemory(":memory:", url=""), r, b)
    st = [j.ask(f"q{i}").status for i in range(10)]
    assert st[:3] == ["OK"] * 3 and set(st[3:]) == {"LIMITED"} and len(r.log) == 3
    t[0] += 61; assert j.ask("again").status == "OK"

def test_daily_call_and_token_budgets_fail_safe():
    b = LLMBudget(_cfg(max_calls_per_day=2))
    b.reserve("viewer", 600); b.reserve("viewer", 600)
    with pytest.raises(BudgetExceeded): b.reserve("owner", 600)
    b2 = LLMBudget(_cfg(max_tokens_per_day=1000)); b2.reserve("viewer", 600)
    with pytest.raises(BudgetExceeded): b2.reserve("viewer", 600)
    with pytest.raises(BudgetExceeded): LLMBudget(_cfg()).reserve("intruder", 1)

def test_missing_usage_charged_conservatively_and_unknown_cost_blocks_cost_budget():
    b = LLMBudget(_cfg(max_cost_usd_per_day="1.00")); r = _router(usage=None)
    j = Jev({"summary": lambda: {}}, SharedMemory(":memory:", url=""), r, b)
    a = j.ask("q1"); assert a.status == "OK"
    st = b.status(); assert st["tokens_charged"] == Jev.MAX_TOKENS and st["cost_usd"] == "UNKNOWN"
    assert j.ask("q2").status == "LIMITED" and len([c for c in r.log if c["ok"]]) == 1

def test_not_configured_no_fabrication_no_note_no_charge(client):
    m = SharedMemory(":memory:", url=""); b = LLMBudget(_cfg())
    rep = Jev({"summary": lambda: {}}, m, LLMRouter(env={}), b).ask("hi", save_note=True, role="owner", may_persist=True)
    assert rep.status == "NOT CONFIGURED" and rep.answer is None and m.count() == 0 and b.status()["calls"] == 0
    from crew import api
    r = client.post("/api/jev", headers=OWN, json={"question": "hi", "save_note": True}).json()
    assert r["status"] == "NOT CONFIGURED" and r["answer"] is None
    assert not [x for x in api.SYS.store.rows("audit_log") if x[3] == "jev_note" and x[2] == "owner"]

def test_request_size_bounded(client):
    assert client.post("/api/jev", headers=VW, json={"question": "x" * 2001}).status_code == 422
    assert client.post("/api/jev", headers=VW, json={"question": ""}).status_code == 422

def test_budget_endpoint_has_no_secrets(client):
    s = client.get("/api/jev/budget", headers=VW).json(); assert "limits" in s and "key" not in str(s).lower()
