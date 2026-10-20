"""FastAPI backend: REST + WebSocket. Tokens from env only. Mode cannot exceed PAPER via API."""
from __future__ import annotations
import asyncio, json, os, secrets
from decimal import Decimal
from fastapi import FastAPI, HTTPException, Header, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .auth import Role, require, Forbidden
from .engine import CrewSystem, ROOT
from .models import Approval
from .modes import Mode, LADDER, gate, Stats
from .desks_synthetic import DESKS, DeskLocked
from . import drills, desk_d5

def _tokens():
    return {v: r for r in Role if (v := os.environ.get(f"CREW_{r.name}_TOKEN"))}
def role_of(token):
    if not token: raise HTTPException(401, "missing token")
    for k, r in _tokens().items():
        if secrets.compare_digest(k, token): return r
    raise HTTPException(401, "bad token")
def auth(authorization, perm):
    tok = authorization.split(" ",1)[1] if authorization and authorization.startswith("Bearer ") else authorization
    r = role_of(tok)
    try: require(r, perm)
    except Forbidden as e: raise HTTPException(403, str(e))
    return r
def jd(o): return json.loads(json.dumps(o, default=lambda x: list(x) if isinstance(x,(set,tuple)) else str(x)))

app = FastAPI(title="Grok Trading Crew (paper only)")
SYS: CrewSystem | None = None
DRILLS: dict = {}; D5: dict = {}
H = Header(None)

@app.on_event("startup")
async def boot():
    global SYS, DRILLS, D5
    SYS = CrewSystem(); await asyncio.to_thread(SYS.run_paper_day)
    p = ROOT/"reports"/"drills-latest.json"
    DRILLS = json.loads(p.read_text()) if p.exists() else {}
    try: D5 = {"replay": await asyncio.to_thread(desk_d5.replay), "gate0": desk_d5.GATE0, "sebi": desk_d5.sebi_gates(desk_d5.OwnerSignals())}
    except Exception as e: D5 = {"error": f"{type(e).__name__}: {e}", "status": desk_d5.STATUS}
    SYS.desks["D5"] = {"desk":"D5","name":"India NSE equities (SEBI)","status":desk_d5.STATUS,"mode":"REPLAY"}

def snap():
    s = SYS; d4 = s.result.get("D4", {})
    return {"mode": s.modes.mode.value, "live_enabled": os.environ.get("LIVE_ENABLED","false"),
            "kill": {"engaged": s.kill.engaged, "reason": s.kill.reason, "desks_halted": sorted(s.kill.desks_halted)},
            "net_pnl_after_costs": d4.get("net_pnl_after_costs"), "fees_paid": d4.get("fees_paid"), "fills": d4.get("fills"),
            "avg_slippage_bps": d4.get("avg_slippage_bps"), "round_trips": d4.get("round_trips"), "wins": d4.get("winning_round_trips"),
            "vetoes": len(d4.get("vetoes", [])), "final_equity": d4.get("final_equity_mtm"), "start_equity": d4.get("start_equity"),
            "recon_drift": d4.get("reconciliation_drift"), "tickets_by_state": s.result.get("tickets_by_state"),
            "ticket_outcomes": s.result.get("ticket_outcomes"), "escalations": s.result.get("escalations"),
            "trace_rows": len(s.store.rows("trace")), "cost": s.result.get("cost"), "variants": s.result.get("strategy_variants_tried"),
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
def trace(authorization: str | None = H, ticket_id: str | None = None, limit: int = 300):
    auth(authorization,"view"); rows = [dict(zip(TC, r)) for r in SYS.store.rows("trace")]
    if ticket_id: rows = [r for r in rows if r["ticket_id"] == ticket_id]
    return rows[-limit:]
@app.get("/api/pnl")
def pnl(authorization: str | None = H):
    auth(authorization,"view"); d = SYS.result["D4"]
    return jd({"paper": {k: d[k] for k in ("start_equity","final_equity_mtm","net_pnl_after_costs","fees_paid","avg_slippage_bps","daily_pnl_realized","equity_curve","reconciliation_drift")},
               "live": None, "note": "paper and live are separate; live does not exist in this build"})
@app.get("/api/markets")
def markets(authorization: str | None = H):
    auth(authorization,"view"); d = SYS.result["D4"]
    return jd({"label": d["source"], "fills": d["fill_log"], "equity_curve": d["equity_curve"], "qa": d["qa"], "vetoes": d["vetoes"]})
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
def post_config(body: CfgIn, authorization: str | None = H):
    r = auth(authorization,"config")
    if any(k.startswith("limit") or k in SYS.limits._d for k in body.data):
        SYS.store.audit(r.value, "config_rejected", "attempt to change risk limits via API")
        raise HTTPException(403, "risk limits are file-only and immutable at runtime")
    v = SYS.config.commit(body.data, r.value, body.note); SYS.store.audit(r.value,"config_commit",f"v{v.version}"); return {"version": v.version}
@app.post("/api/configs/rollback/{ver}")
def rollback(ver: int, authorization: str | None = H):
    r = auth(authorization,"config"); return {"version": SYS.config.rollback(ver, r.value).version}
@app.get("/api/mode")
def get_mode(authorization: str | None = H):
    auth(authorization,"view"); return jd({"mode": SYS.modes.mode.value, "ladder": [m.value for m in LADDER], "api_cap": "PAPER", "log": SYS.modes.log})
class ModeIn(BaseModel): mode: str; desk: str | None = None
@app.post("/api/mode")
def post_mode(body: ModeIn, authorization: str | None = H):
    r = auth(authorization,"mode_change")
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
def approve(body: ApprIn, authorization: str | None = H):
    r = auth(authorization,"approve")
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

@app.websocket("/ws/{channel}")
async def ws(sock: WebSocket, channel: str, token: str = Query("")):
    try: role_of(token)
    except HTTPException: await sock.close(code=4401); return
    await sock.accept()
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
