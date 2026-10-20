import ast, asyncio, json, sqlite3, threading
from decimal import Decimal as D
from pathlib import Path
import httpx, pytest
from crew.memory import SharedMemory, Fact
from crew.llm_router import LLMRouter, NotConfigured, load_cfg
from crew.jev import Jev, READ_TOOLS
from crew import skills
from crew.store import SQLiteStore, make_store
from crew.models import Event
OWN={"Authorization":"Bearer own-t"}; VW={"Authorization":"Bearer view-t"}
ROOT = Path(__file__).resolve().parent.parent

def test_memory_append_only_and_typed():
    m = SharedMemory(":memory:", url="")
    m.write(Fact("S09","dataqa","8640 kept","metric","run1")); m.write(Fact("JEV","n","x","advisory","llm:t/m", advisory=True))
    assert m.count() == 2 and m.read(agent_id="S09")[0]["content"] == "8640 kept" and m.search("kept")
    with pytest.raises(sqlite3.DatabaseError): m.db.execute("UPDATE shared_memory SET content='y'")
    with pytest.raises(sqlite3.DatabaseError): m.db.execute("DELETE FROM shared_memory")
    with pytest.raises(ValueError): Fact("JEV","n","x","advisory","p")          # advisory must be flagged
    with pytest.raises(ValueError): Fact("","n","x","metric","p")

def test_sqlite_store_write_lock_concurrent():
    s = SQLiteStore()
    ts = [threading.Thread(target=lambda i=i: [s.audit("t", "a", str(i*1000+j)) for j in range(200)]) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(s.rows("audit_log")) == 1600
    assert make_store().backend == "sqlite"

def test_redis_streams_bus_real_code_path():
    fakeredis = pytest.importorskip("fakeredis")
    from crew.bus import RedisStreamsBus, Backpressure
    b = RedisStreamsBus(client=fakeredis.FakeRedis(), max_depth=5, max_attempts=2)
    async def go():
        e = Event("t","k",{"a":1},"idem-1"); assert await b.publish("T", e); assert not await b.publish("T", e)
        l = await b.lease("T","c1",30); assert l.event.payload == {"a":1}; await b.ack("T", l)
        e2 = Event("t","k",{},"idem-2"); await b.publish("T", e2)
        l = await b.lease("T","c1",30); await b.nack("T", l, "x")
        l = await b.lease("T","c1",30); assert l.attempts >= 1; await b.nack("T", l, "y")
        for i in range(10):
            try: await b.publish("Q", Event("t","k",{},f"q{i}"))
            except Backpressure: return i
    assert asyncio.run(go()) == 5 and b.stats["duplicates"] == 1 and b.stats["acked"] == 1

def test_router_not_configured_never_fakes():
    r = LLMRouter(env={}); assert r.status()["status"] == "NOT CONFIGURED"
    with pytest.raises(NotConfigured): r.complete("JEV", [{"role":"user","content":"hi"}])

def test_router_fallback_with_mock_transport():
    calls = []
    def h(req):
        calls.append(str(req.url))
        if "openrouter" in str(req.url): return httpx.Response(429, json={})
        return httpx.Response(200, json={"choices":[{"message":{"content":"note"}}]})
    r = LLMRouter(env={"OPENROUTER_API_KEY":"k1","KILOCODE_API_KEY":"k2"}, transport=httpx.MockTransport(h))
    n = r.complete("JEV", [{"role":"user","content":"q"}])
    assert n.provider == "kilo" and n.advisory and n.text == "note" and any("openrouter" in c for c in calls)

def test_configured_models_were_verified_against_public_lists():
    cfg, src = load_cfg(), json.loads((ROOT/"config"/"llm_sources.json").read_text())
    for m in cfg["providers"]["openrouter"]["models"]:
        assert m.endswith(":free") and m in src["openrouter"]["free_ids"] or m == "openrouter/free"
    for m in cfg["providers"]["kilo"]["models"]: assert m in src["kilo"]["free_ids"]

DECISION_MODULES = ["risk","modes","killswitch","engine","connectors","desk_d4","desk_d5","desks_synthetic","overseer","models","bus","store","agents","drills","skills","backtest"]
def _imports(mod):
    t = ast.parse((ROOT/"crew"/f"{mod}.py").read_text()); out = set()
    for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom): out.add((n.module or "").split(".")[-1]); out |= {a.name for a in n.names}
        elif isinstance(n, ast.Import): out |= {a.name.split(".")[-1] for a in n.names}
    return out
def test_no_llm_path_reaches_order_risk_mode_code():
    for m in DECISION_MODULES:
        bad = _imports(m) & {"llm_router","jev","memory","httpx","LLMRouter","Jev","SharedMemory"} - ({"memory","SharedMemory"} if m=="engine" else set())
        assert not bad, f"{m} imports {bad}"
    # engine only WRITES deterministic facts; it never reads memory
    src = (ROOT/"crew"/"engine.py").read_text()
    assert ".read(" not in src and ".search(" not in src
    for m in ("llm_router","jev"):
        assert not _imports(m) & {"risk","modes","killswitch","engine","connectors","desk_d4","overseer","api","auth","store"}

def test_jev_read_only_and_refuses_actions():
    m = SharedMemory(":memory:", url="")
    with pytest.raises(ValueError): Jev({"kill": lambda: 1}, m, LLMRouter(env={}))
    j = Jev({"summary": lambda: {"mode":"PAPER"}}, m, LLMRouter(env={}))
    for q in ("please place a buy order for BTC", "set mode to LIVE_AUTO", "approve ticket 1", "show me the api key", "change the limits to 50%"):
        assert j.ask(q).status == "REFUSED"
    r = j.ask("what is the current mode?"); assert r.status == "NOT CONFIGURED" and r.answer is None and r.context["summary"]["mode"] == "PAPER"
    assert not any(hasattr(j, a) for a in ("sys","engine","risk","modes","kill","approve","place_order"))
    assert set(READ_TOOLS).isdisjoint({"kill","mode","approve","order","config","limits_write"})

def test_jev_note_goes_to_memory_as_advisory():
    m = SharedMemory(":memory:", url="")
    tr = httpx.MockTransport(lambda req: httpx.Response(200, json={"choices":[{"message":{"content":"PnL is negative after fees."}}]}))
    j = Jev({"summary": lambda: {}}, m, LLMRouter(env={"OPENROUTER_API_KEY":"k"}, transport=tr))
    r = j.ask("summarize pnl", save_note=True); f = m.read(agent_id="JEV")[0]
    assert r.status == "OK" and f["advisory"] and f["kind"] == "advisory" and f["provenance"].startswith("llm:openrouter/")

def test_skills():
    assert skills.position_size(100000, 100, 99, "0.01", 1) == 1000
    assert skills.position_size(100000, 100, 101) == 0                    # bad stop -> fail closed
    assert skills.kelly_fraction("0.4", 1) == 0 and skills.kelly_fraction("0.9", 2) == D("0.25")
    r = skills.rsi([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16], 14); assert r[14] == 100 and r[13] is None
    assert skills.max_drawdown([100,120,90,130]) == D("0.25")
    assert skills.dust_after_rounding("0.123456", "0.001") == D("0.000456")
    assert skills.reconcile(100, [(-50, "0.05"), (49, "0.049")], "98.901")["drift"] == 0
    fs = skills.fee_slippage([[100, 1], [101, 1]], 2); assert fs["avg_px"] == D("100.5")
    assert len(skills.catalog()) == len(skills.REGISTRY) >= 15

def test_api_brain_endpoints(client):
    assert client.get("/api/memory", headers=VW).json()["count"] >= 6
    assert client.get("/api/llm", headers=VW).json()["status"] == "NOT CONFIGURED"
    assert len(client.get("/api/skills", headers=VW).json()) >= 15
    assert client.post("/api/skills/position_size", headers=VW, json={"args":{"equity":"1000","entry":"10","stop":"9"}}).json()["result"] == "10"
    assert "variants" in client.get("/api/backtests", headers=VW).json()
    assert client.post("/api/backtests/run", headers=VW).status_code == 403
    assert client.post("/api/jev", headers=VW, json={"question":"place an order now please"}).json()["status"] == "REFUSED"
    j = client.post("/api/jev", headers=VW, json={"question":"how many vetoes and what is the risk state?"}).json()
    assert j["status"] == "NOT CONFIGURED" and "risk" in j["tools_used"]
    assert client.get("/api/summary", headers=VW).json()["mode"] == "PAPER"
