"""FastAPI backend: REST + WebSocket. Tokens from env only. Mode cannot exceed PAPER via API."""
from __future__ import annotations
import asyncio, json, os, secrets
from pathlib import Path
from decimal import Decimal
from fastapi import FastAPI, HTTPException, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .auth import Role, require, Forbidden
from .engine import CrewSystem, ROOT
from .models import Approval
from .modes import Mode, LADDER, gate, Stats
from .desks_synthetic import DESKS, DeskLocked
from . import drills, desk_d5, skills as skills_mod, backtest as backtest_mod
from .store import make_store
from .memory import SharedMemory, Fact
from .llm_router import LLMRouter
from .jev import Jev
from . import metrics as metrics_mod

def _tokens():
    return {v: r for r in Role if (v := os.environ.get(f"CREW_{r.name}_TOKEN"))}
def role_of(token):
    if not token: raise HTTPException(401, "missing token")
    for k, r in _tokens().items():
        if secrets.compare_digest(k, token): return r
    raise HTTPException(401, "bad token")
OWNER_TOTP_PERMS = {"approve", "mode_change", "config"}
def totp_ok(code: str | None) -> bool:
    """Optional TOTP for owner actions. Disabled when CREW_OWNER_TOTP_SECRET is unset (env/.env only)."""
    sec = os.environ.get("CREW_OWNER_TOTP_SECRET", "")
    if not sec: return True
    import pyotp
    return bool(code) and pyotp.TOTP(sec).verify(code, valid_window=1)
def auth(authorization, perm, totp: str | None = None):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, "Authorization: Bearer <token> header required")
    r = role_of(authorization.split(" ",1)[1])
    try: require(r, perm)
    except Forbidden as e: raise HTTPException(403, str(e))
    if perm in OWNER_TOTP_PERMS and not totp_ok(totp): raise HTTPException(401, "valid X-TOTP header required for owner actions")
    return r
def jd(o): return json.loads(json.dumps(o, default=lambda x: list(x) if isinstance(x,(set,tuple)) else str(x)))

app = FastAPI(title="Grok Trading Crew (paper only)")
SYS: CrewSystem | None = None
DRILLS: dict = {}; D5: dict = {}
MEM: SharedMemory | None = None; ROUTER: LLMRouter | None = None; JEV: Jev | None = None
BOOT_READY = False
H = Header(None)
TOTP = Header(None, alias="X-TOTP")

@app.on_event("startup")
async def boot():
    global SYS, DRILLS, D5, MEM, ROUTER, JEV, BOOT_READY
    mp = os.environ.get("CREW_MEMORY_PATH", str(ROOT/"var"/"shared_memory.db"))
    if mp != ":memory:": Path(mp).parent.mkdir(parents=True, exist_ok=True)
    MEM = SharedMemory(mp); ROUTER = LLMRouter()
    SYS = CrewSystem(store=make_store(), memory=MEM); await asyncio.to_thread(SYS.run_paper_day)
    p = ROOT/"reports"/"drills-latest.json"
    DRILLS = json.loads(p.read_text()) if p.exists() else {}
    try: D5 = {"replay": await asyncio.to_thread(desk_d5.replay), "gate0": desk_d5.GATE0, "sebi": desk_d5.sebi_gates(desk_d5.OwnerSignals())}
    except Exception as e: D5 = {"error": f"{type(e).__name__}: {e}", "status": desk_d5.STATUS}
    SYS.desks["D5"] = {"desk":"D5","name":"India NSE equities (SEBI)","status":desk_d5.STATUS,"mode":"REPLAY"}
    BOOT_READY = True

@app.get("/health/live")
def health_live(): return {"status": "ok"}

@app.get("/health/ready")
def health_ready():
    ready = bool(BOOT_READY and SYS is not None and SYS.result and MEM is not None and ROUTER is not None and _tokens())
    return Response(json.dumps({"status": "ready" if ready else "starting", "ready": ready}),
                    status_code=200 if ready else 503, media_type="application/json")

def _cost(eng: dict) -> dict:
    t = ROUTER.totals() if ROUTER else {"tokens": 0, "cost_usd": "0", "calls": 0}
    cost = t["cost_usd"] if eng.get("llm_cost_usd") == "0" else "UNKNOWN"
    return {**eng, "llm_tokens": eng.get("llm_tokens", 0) + t["tokens"], "llm_cost_usd": cost, "engine": dict(eng), "router": t,
            "note": "engine agents make 0 LLM calls; router totals come from provider usage fields and verified prices (config/llm_pricing.json); unknown price => UNKNOWN"}

def snap():
    s = SYS; d4 = s.result.get("D4", {})
    return {"mode": s.modes.mode.value, "live_enabled": "false (hard-disabled by build policy)",
            "kill": {"engaged": s.kill.engaged, "reason": s.kill.reason, "desks_halted": sorted(s.kill.desks_halted)},
            "net_pnl_after_costs": d4.get("net_pnl_after_costs"), "fees_paid": d4.get("fees_paid"), "fills": d4.get("fills"),
            "avg_slippage_bps": d4.get("avg_slippage_bps"), "round_trips": d4.get("round_trips"), "wins": d4.get("winning_round_trips"),
            "vetoes": len(d4.get("vetoes", [])), "final_equity": d4.get("final_equity_mtm"), "start_equity": d4.get("start_equity"),
            "recon_drift": d4.get("reconciliation_drift"), "tickets_by_state": s.result.get("tickets_by_state"),
            "ticket_outcomes": s.result.get("ticket_outcomes"), "escalations": s.result.get("escalations"),
            "trace_rows": len(s.store.rows("trace")), "cost": _cost(s.result.get("cost") or {}), "run_id": s.result.get("run_id"), "variants": s.result.get("strategy_variants_tried"),
            "live_pnl": None, "live_note": "no live trading exists in this build", "source": d4.get("source"),
            "agents_enabled": sum(a.state=="ENABLED" for a in s.reg.all()), "agents_total": 50}

@app.get("/api/whoami")
def whoami(authorization: str | None = H): return {"role": auth(authorization, "view").value}
@app.get("/api/summary")
def summary(authorization: str | None = H): auth(authorization,"view"); return jd(snap())
@app.get("/api/agents")
def agents(authorization: str | None = H): auth(authorization,"view"); return [a.metrics() for a in SYS.reg.all()]
@app.get("/api/desks")
def desks(authorization: str | None = H): auth(authorization,"view"); return SYS.desks
@app.get("/api/india")
def india(authorization: str | None = H): auth(authorization,"view"); return jd(D5)
@app.get("/api/tickets")
def tickets(authorization: str | None = H):
    auth(authorization,"view")
    return jd([{"id":t.ticket_id,"desk":t.desk,"instrument":t.instrument,"state":t.state.value,"history":t.history,"flags":sorted(t.flags)} for t in SYS.main.tickets.values()])
TC = ["trace_id","ts","ticket_id","agent_id","crew","stage","msg_type","content","evidence","confidence"]
@app.get("/api/trace")
def trace(authorization: str | None = H, ticket_id: str | None = None, limit: int = Query(300, ge=0, le=2000)):
    auth(authorization,"view"); rows = [dict(zip(TC, r)) for r in SYS.store.rows("trace")]
    if ticket_id: rows = [r for r in rows if r["ticket_id"] == ticket_id]
    return rows[-limit:] if limit else []
@app.get("/api/pnl")
def pnl(authorization: str | None = H):
    auth(authorization,"view"); d = SYS.result["D4"]
    return jd({"paper": {k: d[k] for k in ("start_equity","final_equity_mtm","net_pnl_after_costs","fees_paid","avg_slippage_bps","daily_pnl_realized","equity_curve","reconciliation_drift")},
               "live": None, "note": "paper and live are separate; live does not exist in this build"})
@app.get("/api/markets")
def markets(authorization: str | None = H):
    auth(authorization,"view"); d = SYS.result["D4"]
    return jd({"label": d["source"], "fills": d["fill_log"], "equity_curve": d["equity_curve"], "qa": d["qa"], "vetoes": d["vetoes"]})
@app.get("/api/candles")
def candles(authorization: str | None = H, symbol: str = "BTCUSDT", interval: int = 900):
    """OHLC of the replay mid price (synthetic sample) bucketed by `interval` seconds, plus this run's paper fills."""
    auth(authorization,"view")
    if interval < 60 or interval > 86400: raise HTTPException(400, "interval must be 60..86400 s")
    out = {}
    for t in SYS._ticks:
        if t.symbol != symbol: continue
        b = t.ts - t.ts % interval; m = t.mid; c = out.get(b)
        out[b] = [b, m, m, m, m] if c is None else [b, c[1], max(c[2], m), min(c[3], m), m]
    fills = [f for f in SYS.result["D4"]["fill_log"] if f["symbol"] == symbol]
    return jd({"label": "synthetic replay sample (mid price), not real market data", "symbol": symbol, "interval": interval,
               "symbols": sorted({t.symbol for t in SYS._ticks}),
               "candles": [{"time": b, "open": str(o), "high": str(h), "low": str(l), "close": str(c)} for b, o, h, l, c in out.values()],
               "fills": fills})
@app.get("/api/research")
def research(authorization: str | None = H): auth(authorization,"view"); return SYS.result["synthetic_desks"]
@app.get("/api/reports")
def reports(authorization: str | None = H):
    auth(authorization,"view"); return sorted(p.name for p in (ROOT/"reports").glob("*") if p.is_file())
@app.get("/api/reports/{name}")
def report(name: str, authorization: str | None = H):
    auth(authorization,"view"); base = (ROOT/"reports").resolve(); p = (base/name).resolve()
    if p.parent != base or not p.exists(): raise HTTPException(404)
    return FileResponse(p)
@app.get("/api/risk")
def risk(authorization: str | None = H):
    auth(authorization,"view")
    return jd({"limits": dict(SYS.limits._d), "limits_sha256": SYS.limits.sha256, "limits_file_ok": SYS.auditor.check(),
               "kill": {"engaged": SYS.kill.engaged, "reason": SYS.kill.reason, "desks_halted": sorted(SYS.kill.desks_halted)},
               "risk_events": [list(r) for r in SYS.store.rows("risk_events")][-100:], "vetoes": SYS.result["D4"]["vetoes"],
               "halted_reason": SYS.risk.halted_reason, "drills": DRILLS})
@app.get("/api/risk/utilisation")
def risk_util(authorization: str | None = H):
    auth(authorization,"view"); ru = SYS.risk_util
    return jd({"label": "value/limit per real limit from config/limits.json; >= 1 = breach (at-limit counts). 'last' = most recent risk check in this run; 'peak' = max over all checks",
               "limits": dict(SYS.limits._d), "checks": ru["checks"], "last": ru["last"], "peak": ru["peak"]})
@app.get("/api/drills")
def get_drills(authorization: str | None = H): auth(authorization,"view"); return DRILLS
@app.post("/api/drills/run")
def run_drills(authorization: str | None = H):
    global DRILLS; auth(authorization,"kill"); DRILLS = jd(drills.run_all()); return DRILLS
@app.get("/api/connectors")
def connectors(authorization: str | None = H):
    auth(authorization,"view"); return [{**c.info(), "health": c.health()} for c in SYS.connectors]
@app.post("/api/connectors/{name}/test")
def test_conn(name: str, authorization: str | None = H):
    auth(authorization,"view")
    for c in SYS.connectors:
        if c.manifest.name == name: return c.test()
    raise HTTPException(404)
@app.get("/api/configs")
def configs(authorization: str | None = H):
    auth(authorization,"view"); return [{"version":v.version,"author":v.author,"note":v.note,"sha256":v.sha256,"data":v.data} for v in SYS.config.versions]
class CfgIn(BaseModel): data: dict; note: str = ""
@app.post("/api/configs")
def post_config(body: CfgIn, authorization: str | None = H, x_totp: str | None = TOTP):
    r = auth(authorization,"config", x_totp)
    if any(k.startswith("limit") or k in SYS.limits._d for k in body.data):
        SYS.store.audit(r.value, "config_rejected", "attempt to change risk limits via API")
        raise HTTPException(403, "risk limits are file-only and immutable at runtime")
    v = SYS.config.commit(body.data, r.value, body.note); SYS.store.audit(r.value,"config_commit",f"v{v.version}"); return {"version": v.version}
@app.post("/api/configs/rollback/{ver}")
def rollback(ver: int, authorization: str | None = H, x_totp: str | None = TOTP):
    r = auth(authorization,"config", x_totp); return {"version": SYS.config.rollback(ver, r.value).version}
@app.get("/api/mode")
def get_mode(authorization: str | None = H):
    auth(authorization,"view"); return jd({"mode": SYS.modes.mode.value, "ladder": [m.value for m in LADDER], "api_cap": "PAPER", "log": SYS.modes.log})
class ModeIn(BaseModel): mode: str; desk: str | None = None
@app.post("/api/mode")
def post_mode(body: ModeIn, authorization: str | None = H, x_totp: str | None = TOTP):
    r = auth(authorization,"mode_change", x_totp)
    try: to = Mode(body.mode)
    except ValueError: raise HTTPException(400, "unknown mode")
    if body.desk == "D5" and to is not Mode.REPLAY:
        g = desk_d5.sebi_gates(desk_d5.OwnerSignals())
        raise HTTPException(403, {"error": "D5 cannot leave REPLAY", "failed": [c["gate"] for c in g["checklist"] if not c["ok"]]})
    if body.desk in DESKS:
        try: DESKS[body.desk].set_mode(to)
        except DeskLocked as e: raise HTTPException(403, str(e))
        return {"desk": body.desk, "mode": "REPLAY"}
    if LADDER.index(to) > LADDER.index(Mode.PAPER):
        SYS.store.audit(r.value, "mode_rejected", f"{to.value}: API cannot exceed PAPER")
        g = gate(SYS.modes.mode, to, Stats(), None)
        raise HTTPException(403, {"error": "API cannot set mode above PAPER in this build", "gate_reasons": list(g.reasons)})
    if LADDER.index(to) <= LADDER.index(SYS.modes.mode): SYS.modes.mode = to
    else:
        g = SYS.modes.promote(to, Stats())
        if not g.allowed: raise HTTPException(403, {"gate_reasons": list(g.reasons)})
    SYS.store.audit(r.value, "mode", to.value); return {"mode": SYS.modes.mode.value}
class KillIn(BaseModel): reason: str = "manual kill"
@app.post("/api/kill")
def kill(body: KillIn, authorization: str | None = H):
    r = auth(authorization,"kill"); SYS.engage_kill(body.reason, r.value)
    return {"engaged": True, "desks_halted": sorted(SYS.kill.desks_halted)}
@app.get("/api/approvals")
def approvals(authorization: str | None = H): auth(authorization,"view"); return jd(SYS.approvals)
class ApprIn(BaseModel): subject: str; decision: str
@app.post("/api/approvals")
def approve(body: ApprIn, authorization: str | None = H, x_totp: str | None = TOTP):
    r = auth(authorization,"approve", x_totp)
    if body.decision not in ("APPROVE","REJECT"): raise HTTPException(400, "decision must be APPROVE or REJECT")
    try: a = Approval(body.subject, r.value, body.decision).signed()
    except Exception as e: raise HTTPException(503, f"cannot sign: {e}")
    rec = {"subject":a.subject,"approver":a.approver,"decision":a.decision,"ts":a.ts,"signature":a.signature,"verified":a.verify()}
    if body.subject.startswith("promote:") and "->" in body.subject:
        try:
            frm, to = body.subject[8:].split("->"); g = gate(Mode(frm), Mode(to), Stats(), a)
            rec["gate_result"] = {"allowed": g.allowed, "reasons": list(g.reasons)}
        except ValueError: raise HTTPException(400, "bad promote subject")
    SYS.approvals.append(rec); SYS.store.audit(r.value, "approval", f"{a.subject} {a.decision}"); return rec
@app.get("/api/audit")
def audit(authorization: str | None = H): auth(authorization,"view"); return [list(r) for r in SYS.store.rows("audit_log")]

def _backtests():
    p = ROOT/"reports"/"backtests-latest.json"
    return json.loads(p.read_text()) if p.exists() else {"label": "no backtest run yet", "variants": []}
@app.get("/api/backtests")
def backtests(authorization: str | None = H): auth(authorization,"view"); return _backtests()
@app.post("/api/backtests/run")
def run_backtests(authorization: str | None = H, x_totp: str | None = TOTP):
    r = auth(authorization,"config", x_totp); res = backtest_mod.run(); backtest_mod.save(res)
    SYS.store.audit(r.value, "backtest_run", f"{res['variants_tried']} variants"); return res
@app.get("/api/v1/metrics")
def prom(authorization: str | None = H):
    """Prometheus text format. Requires a viewer token (Prometheus: authorization: {type: Bearer, credentials_file: ...})."""
    auth(authorization, "view")
    body, ctype = metrics_mod.render(SYS.telemetry, SYS.kill.engaged, SYS.modes.mode.value, SYS.result.get("run_id"), DRILLS)
    return Response(body, media_type=ctype)
@app.get("/api/memory")
def memory(authorization: str | None = H, q: str | None = Query(None, max_length=200), topic: str | None = Query(None, max_length=100), agent_id: str | None = Query(None, max_length=32), limit: int = Query(200, ge=0, le=500)):
    auth(authorization,"view")
    return {"backend": MEM.backend, "count": MEM.count(), "facts": MEM.search(q, limit) if q else MEM.read(topic, agent_id, limit)}
@app.get("/api/skills")
def skills(authorization: str | None = H): auth(authorization,"view"); return skills_mod.catalog()
class SkillIn(BaseModel): args: dict = {}
@app.post("/api/skills/{name}")
def call_skill(name: str, body: SkillIn, authorization: str | None = H):
    auth(authorization,"research")
    if name not in skills_mod.REGISTRY: raise HTTPException(404)
    if len(json.dumps(body.args, default=str)) > 16384: raise HTTPException(413, "skill arguments exceed 16 KiB")
    try: return jd({"skill": name, "result": skills_mod.REGISTRY[name](**body.args)})
    except Exception as e: raise HTTPException(400, f"{type(e).__name__}: {e}")
@app.get("/api/llm")
def llm(authorization: str | None = H): auth(authorization,"view"); return {**ROUTER.status(), "recent_calls": ROUTER.log[-50:]}
def _jev():
    global JEV
    if JEV is None:
        JEV = Jev({"summary": snap, "risk": lambda: {"limits": dict(SYS.limits._d), "kill": SYS.kill.engaged, "vetoes": SYS.result["D4"]["vetoes"], "drills": DRILLS},
                   "audit": lambda: [list(r) for r in SYS.store.rows("audit_log")][-50:],
                   "reports": lambda: sorted(p.name for p in (ROOT/"reports").glob("*") if p.is_file()),
                   "memory": lambda: MEM.read(limit=20), "skills": skills_mod.catalog, "desks": lambda: SYS.desks,
                   "india": lambda: {"gate0": D5.get("gate0"), "sebi": D5.get("sebi")}, "backtests": _backtests}, MEM, ROUTER)
    return JEV
class JevIn(BaseModel): question: str; save_note: bool = False
@app.post("/api/jev")
def jev(body: JevIn, authorization: str | None = H):
    r = auth(authorization,"view"); rep = _jev().ask(body.question, body.save_note)
    SYS.store.audit(r.value, "jev_ask", rep.status); return jd(rep.__dict__)

@app.websocket("/ws/{channel}")
async def ws(sock: WebSocket, channel: str):
    """First-message auth: client must send {"auth": "<token>"} within 5 s. Tokens are never accepted in the URL."""
    await sock.accept()
    try:
        msg = await asyncio.wait_for(sock.receive_json(), 5)
        role = role_of(msg.get("auth") if isinstance(msg, dict) else None)
        require(role, "view")
        if channel not in {"summary", "agents", "trace", "pnl"}:
            await sock.close(code=4404); return
    except Exception:
        await sock.close(code=4401); return
    try:
        while True:
            if channel == "agents": payload = [a.metrics() for a in SYS.reg.all()]
            elif channel == "trace": payload = [dict(zip(TC, r)) for r in SYS.store.rows("trace")[-30:]]
            else: payload = snap()
            await sock.send_json({"channel": channel, "data": jd(payload)}); await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError): pass

app.mount("/static", StaticFiles(directory=ROOT/"web"), name="static")
@app.get("/")
def index(): return FileResponse(ROOT/"web"/"index.html")
