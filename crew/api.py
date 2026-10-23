"""FastAPI backend: REST + WebSocket. Tokens from env only. Live promotion requires verified gates."""
from __future__ import annotations
import asyncio, json, os, secrets
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from decimal import Decimal
from fastapi import FastAPI, HTTPException, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
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
from .llm_budget import LLMBudget
from . import metrics as metrics_mod
from .orderbook import L2Book
from .live_market import BinancePublicMarketFeed
from .connectors import execution_status

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

SYS: CrewSystem | None = None
DRILLS: dict = {}; D5: dict = {}
MEM: SharedMemory | None = None; ROUTER: LLMRouter | None = None; JEV: Jev | None = None
LIVE_FEED: BinancePublicMarketFeed | None = None
LIVE_FEED_ERROR: str | None = None
BOOT_READY = False
H = Header(None)
TOTP = Header(None, alias="X-TOTP")

async def boot():
    global SYS, DRILLS, D5, MEM, ROUTER, JEV, BOOT_READY, LIVE_FEED, LIVE_FEED_ERROR
    mp = os.environ.get("CREW_MEMORY_PATH", str(ROOT/"var"/"shared_memory.db"))
    if mp != ":memory:": Path(mp).parent.mkdir(parents=True, exist_ok=True)
    ledger_path = os.environ.get("CREW_LEDGER_PATH", str(ROOT/"var"/"trading_crew.db"))
    if ledger_path != ":memory:" and not os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://")):
        Path(ledger_path).parent.mkdir(parents=True, exist_ok=True)
    MEM = SharedMemory(mp); ROUTER = LLMRouter()
    SYS = CrewSystem(store=make_store(sqlite_path=ledger_path), memory=MEM); await asyncio.to_thread(SYS.run_paper_day)
    p = ROOT/"reports"/"drills-latest.json"
    DRILLS = json.loads(p.read_text()) if p.exists() else {}
    try: D5 = {"replay": await asyncio.to_thread(desk_d5.replay), "gate0": desk_d5.GATE0, "sebi": desk_d5.sebi_gates(desk_d5.OwnerSignals())}
    except Exception as e: D5 = {"error": f"{type(e).__name__}: {e}", "status": desk_d5.STATUS}
    SYS.desks["D5"] = {"desk":"D5","name":"India NSE equities (SEBI)","status":desk_d5.STATUS,"mode":"REPLAY"}
    live_data_enabled = os.environ.get("CREW_LIVE_MARKET_DATA", "true").strip().lower() in {"1", "true", "yes", "on"}
    if live_data_enabled:
        try:
            LIVE_FEED = BinancePublicMarketFeed()
            await LIVE_FEED.start()
            SYS.desks["D4"]["market_data"] = "LIVE_READ_ONLY"
        except Exception as e:
            LIVE_FEED = None
            LIVE_FEED_ERROR = f"{type(e).__name__}: {str(e)[:160]}"
    else:
        LIVE_FEED = None
        LIVE_FEED_ERROR = "disabled by CREW_LIVE_MARKET_DATA"
    BOOT_READY = True

async def shutdown():
    if LIVE_FEED is not None:
        await LIVE_FEED.stop()

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Start the application services once and always release them on shutdown."""
    try:
        await boot()
        yield
    finally:
        await shutdown()

app = FastAPI(title="Trading Crew (read-only live market data + paper execution)", lifespan=lifespan)

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
    return {"mode": s.modes.mode.value, "live_enabled": "not configured (no venue execution client)",
            "execution": execution_status("binance"),
            "kill": {"engaged": s.kill.engaged, "reason": s.kill.reason, "desks_halted": sorted(s.kill.desks_halted), "recovered_after_restart": s.kill.recovered},
            "net_pnl_after_costs": d4.get("net_pnl_after_costs"), "fees_paid": d4.get("fees_paid"), "fills": d4.get("fills"),
            "avg_slippage_bps": d4.get("avg_slippage_bps"), "round_trips": d4.get("round_trips"), "wins": d4.get("winning_round_trips"),
            "vetoes": len(d4.get("vetoes", [])), "final_equity": d4.get("final_equity_mtm"), "start_equity": d4.get("start_equity"),
            "recon_drift": d4.get("reconciliation_drift"), "tickets_by_state": s.result.get("tickets_by_state"),
            "ticket_outcomes": s.result.get("ticket_outcomes"), "escalations": s.result.get("escalations"),
            "trace_rows": len(s.store.rows("trace")), "cost": _cost(s.result.get("cost") or {}), "run_id": s.result.get("run_id"), "variants": s.result.get("strategy_variants_tried"),
            "live_pnl": None, "live_note": "no live trading exists in this build", "source": d4.get("source"),
            "agents_enabled": sum(a.state=="ENABLED" for a in s.reg.all()), "agents_total": len(s.reg.all()),
            "provenance": d4.get("provenance"),
            "market_data": LIVE_FEED.snapshot() if LIVE_FEED else {"status": "DISABLED", "last_error": LIVE_FEED_ERROR,
                "read_only": True, "order_execution_available": False}}

@app.get("/api/whoami")
def whoami(authorization: str | None = H): return {"role": auth(authorization, "view").value}
@app.get("/api/summary")
def summary(authorization: str | None = H): auth(authorization,"view"); return jd(snap())
@app.get("/api/execution/status")
def get_execution_status(authorization: str | None = H):
    auth(authorization, "view")
    return jd({**execution_status("binance"), "current_mode": SYS.modes.mode.value,
               "paper_kill_engaged": SYS.kill.engaged})
@app.get("/api/execution/gates")
def get_execution_gates(authorization: str | None = H):
    """Return gate evidence from this process; never infer missing live evidence as a pass."""
    auth(authorization, "view")
    d4 = SYS.result.get("D4", {})
    provenance = d4.get("provenance") or {}
    live_exec = execution_status("binance")
    market = LIVE_FEED.snapshot() if LIVE_FEED else {"status": "DISABLED"}
    drill_values = DRILLS.values() if isinstance(DRILLS, dict) else ()
    local_drills_ok = bool(DRILLS) and all(isinstance(row, dict) and row.get("passed") is True for row in drill_values)
    approvals_ok = any(
        row.get("subject") == "promote:PAPER->LIVE_APPROVAL" and row.get("decision") == "APPROVE"
        and row.get("verified") is True for row in SYS.approvals
    )
    pnl_value = d4.get("net_pnl_after_costs")
    pnl_negative = False
    try:
        pnl_negative = pnl_value is not None and Decimal(str(pnl_value)) <= 0
    except Exception:
        pass
    gates = [
        {"id": "public_market_data", "status": "PASS" if market.get("status") == "CONNECTED" else "INCOMPLETE",
         "detail": f"public feed status: {market.get('status', 'UNKNOWN')}; read-only"},
        {"id": "testnet_adapter_contract", "status": "PASS_LOCAL_ONLY",
         "detail": "Binance Spot Testnet-only REST client has offline contract tests; no Testnet credentials or remote order lifecycle have been verified"},
        {"id": "strategy_validation", "status": "NOT_PASSED",
         "detail": ("current strategy run has non-positive net PnL on synthetic replay; no edge established"
                    if pnl_negative else "no verified historical and out-of-sample strategy evidence")},
        {"id": "historical_out_of_sample", "status": "PASS" if provenance.get("verified_historical") and provenance.get("live") else "NOT_PASSED",
         "detail": "requires independently sourced historical data and a held-out evaluation"},
        {"id": "30_day_paper", "status": "NOT_PASSED",
         "detail": "no durable, qualifying 30-day live-data paper record is registered"},
        {"id": "account_authentication", "status": "PASS" if live_exec["account_authenticated"] else "NOT_CONFIGURED",
         "detail": "authenticated account permissions are not connected"},
        {"id": "live_order_adapter", "status": "PASS" if live_exec["order_submission_available"] else "NOT_IMPLEMENTED",
         "detail": live_exec["reason"]},
        {"id": "exchange_reconciliation_and_kill", "status": "PASS" if live_exec["order_submission_available"] else "NOT_TESTED",
         "detail": "no private order/account stream or exchange-side cancel/flatten integration"},
        {"id": "local_risk_drills", "status": "PASS_LOCAL_ONLY" if local_drills_ok else "NOT_PASSED",
         "detail": "local deterministic risk drills; these do not validate exchange order behavior"},
        {"id": "signed_owner_approval", "status": "PRESENT" if approvals_ok else "NOT_PRESENT",
         "detail": "approval is necessary and cannot substitute for failed evidence gates"},
    ]
    promotion_allowed = live_exec["order_submission_available"] and all(
        row["status"] in {"PASS", "PASS_LOCAL_ONLY", "PRESENT"} for row in gates
    )
    return {"venue": "binance", "mode": SYS.modes.mode.value, "live_enabled_flag": live_exec["live_enabled_flag"],
            "order_submission_available": live_exec["order_submission_available"], "promotion_allowed": promotion_allowed,
            "gates": gates, "checked_at_utc": datetime.now(timezone.utc).isoformat()}
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
    return jd({"paper": {k: d[k] for k in ("start_equity","final_equity_mtm","net_pnl_after_costs","fees_paid","avg_slippage_bps","daily_pnl_realized","equity_curve","reconciliation_drift","regime_stratification","regime_stratification_note")},
               "live": None, "note": "paper and live are separate; live does not exist in this build", "provenance": d["provenance"]})
@app.get("/api/markets")
def markets(authorization: str | None = H):
    auth(authorization,"view"); d = SYS.result["D4"]
    return jd({"label": d["source"], "provenance": d["provenance"], "fills": d["fill_log"], "equity_curve": d["equity_curve"], "qa": d["qa"], "vetoes": d["vetoes"]})

@app.get("/api/market-data")
def market_data(authorization: str | None = H):
    """Current public live prices. Read-only; this route never reads account or execution state."""
    auth(authorization, "view")
    if LIVE_FEED is None:
        return {"source": "Binance Spot public market data", "status": "DISABLED", "read_only": True,
                "authenticated": False, "account_data_available": False, "order_execution_available": False,
                "symbols": [], "quotes": {}, "last_error": LIVE_FEED_ERROR,
                "note": "Configure CREW_LIVE_MARKET_DATA=true to enable the public feed."}
    return jd(LIVE_FEED.snapshot())

@app.get("/api/market-data/candles")
def market_data_candles(authorization: str | None = H, symbol: str = "BTCUSDT",
                        interval: int = Query(60), limit: int = Query(500, ge=1, le=1000)):
    """Live public spot candles, bootstrapped from Binance public REST and updated by its market stream."""
    auth(authorization, "view")
    if LIVE_FEED is None:
        return {"source": "Binance Spot public market data", "data_status": "DISABLED",
                "symbol": symbol.upper(), "interval_seconds": interval, "candles": [], "read_only": True,
                "error": LIVE_FEED_ERROR}
    try:
        return jd(LIVE_FEED.candles(symbol, interval, limit))
    except ValueError as e:
        raise HTTPException(400, str(e))
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
               "fills": fills, "provenance": SYS.result["D4"]["provenance"]})
@app.get("/api/book")
def book(authorization: str | None = H, symbol: str = "BTCUSDT", depth: int = Query(10, ge=1, le=50)):
    """Last recorded L2 snapshot of the offline replay tape for `symbol` (synthetic sample, not a live feed)."""
    auth(authorization,"view"); last = None
    for t in SYS._ticks:
        if t.symbol == symbol: last = t
    if last is None: raise HTTPException(404, "no ticks for symbol")
    b = L2Book.from_row({"symbol": last.symbol, "ts": last.ts, "bids": [list(x) for x in last.bids], "asks": [list(x) for x in last.asks]})
    return jd({"label": "offline replay L2 snapshot (synthetic sample), last tick of the run", "symbol": symbol, "ts": last.ts,
               "bids": [[str(p), str(q)] for p, q in b.bids[:depth]], "asks": [[str(p), str(q)] for p, q in b.asks[:depth]],
               "mid": str(b.mid), "spread_bps": str(b.spread_bps()), "provenance": SYS.result["D4"]["provenance"]})
@app.get("/api/pipeline")
def pipeline(authorization: str | None = H):
    """Per-stage counts from this run's real trace, telemetry and ledger. Nothing here is estimated."""
    auth(authorization,"view"); d4 = SYS.result["D4"]; tel = SYS.telemetry; rows = SYS.store.rows("trace")
    by = {}
    for r in rows: by.setdefault(r[5], []).append(r)
    last = lambda st: (by.get(st) or [None])[-1]
    def row(r): return None if r is None else {"ts": r[1], "agent": r[3], "type": r[6], "content": r[7]}
    qa = d4["qa"]
    stages = [
        {"stage": "INGEST", "agent": "S01/S09", "status": "OK" if qa["kept"] else "NO DATA", "detail": f"{qa['kept']}/{qa['input_rows']} ticks kept"},
        {"stage": "SCAN", "agent": "MAIN", "status": "OK" if by.get("open") else "NO DATA", "detail": f"{len(by.get('open', []))} tickets opened"},
        {"stage": "LANES", "agent": "S10/S14", "status": "OK" if by.get("lane") else "NO DATA", "detail": f"{len(by.get('lane', []))} lane verdicts; quorum met {tel['quorum'].get('met', 0)}, disagree {tel['quorum'].get('disagree', 0)}"},
        {"stage": "RISK", "agent": "S34", "status": "VETO" if d4["vetoes"] else ("OK" if SYS.risk_util["checks"] else "NO DATA"), "detail": f"{SYS.risk_util['checks']} checks, {len(d4['vetoes'])} vetoes"},
        {"stage": "FILL", "agent": "S36", "status": "OK" if d4["fills"] else "NO DATA", "detail": f"{d4['fills']} paper fills"},
        {"stage": "RECONCILE", "agent": "S45", "status": "OK" if Decimal(str(d4["reconciliation_drift"])) == 0 else "DRIFT", "detail": f"drift {d4['reconciliation_drift']}"},
        {"stage": "KILL", "agent": "risk", "status": "ENGAGED" if SYS.kill.engaged else "ARMED", "detail": SYS.kill.reason or "not engaged"}]
    return jd({"run_id": SYS.result.get("run_id"), "stages": stages, "last_decision": row(last("arbiter")), "last_lane": row(last("lane")),
               "last_fill": row(last("fill")), "intents_submitted": tel["intents_submitted"], "rejects": dict(tel["rejects"])})
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
               "kill": {"engaged": SYS.kill.engaged, "reason": SYS.kill.reason, "desks_halted": sorted(SYS.kill.desks_halted), "recovered_after_restart": SYS.kill.recovered},
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
    global DRILLS; r = auth(authorization,"kill"); DRILLS = jd(drills.run_all())
    SYS.store.audit(r.value, "drills_run", ",".join(f"{k}:{'PASS' if v.get('passed') else 'FAIL'}" for k, v in DRILLS.items())); return DRILLS
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
    r = auth(authorization,"config", x_totp); v = SYS.config.rollback(ver, r.value)
    SYS.store.audit(r.value, "config_rollback", f"to v{ver} -> v{v.version}"); return {"version": v.version}
@app.get("/api/mode")
def get_mode(authorization: str | None = H):
    auth(authorization,"view"); return jd({"mode": SYS.modes.mode.value, "ladder": [m.value for m in LADDER],
        "promotion_policy": "verified evidence + signed approval + configured venue execution",
        "execution": execution_status("binance"), "log": SYS.modes.log})
class ModeIn(BaseModel): mode: str; desk: str | None = None
def _promotion_evidence(to: Mode):
    subject = f"promote:{SYS.modes.mode.value}->{to.value}"
    row = next((x for x in reversed(SYS.approvals) if x.get("subject") == subject), None)
    approval = None if row is None else Approval(row["subject"], row["approver"], row["decision"], row["ts"], row["signature"])
    stats = getattr(SYS, "mode_stats", Stats())
    return stats if isinstance(stats, Stats) else Stats(), approval
@app.post("/api/mode")
def post_mode(body: ModeIn, authorization: str | None = H, x_totp: str | None = TOTP):
    r = auth(authorization,"mode_change", x_totp)
    try: to = Mode(body.mode)
    except ValueError: raise HTTPException(400, "unknown mode")
    if body.desk == "D5" and to is not Mode.REPLAY:
        g = desk_d5.sebi_gates(desk_d5.OwnerSignals()); SYS.store.audit(r.value, "mode_rejected", f"D5 {to.value}: SEBI gates")
        raise HTTPException(403, {"error": "D5 cannot leave REPLAY", "failed": [c["gate"] for c in g["checklist"] if not c["ok"]]})
    if body.desk in DESKS:
        try: DESKS[body.desk].set_mode(to)
        except DeskLocked as e:
            SYS.store.audit(r.value, "mode_rejected", f"{body.desk} {to.value}: desk locked"); raise HTTPException(403, str(e))
        SYS.store.audit(r.value, "desk_mode", f"{body.desk} {to.value}")
        return {"desk": body.desk, "mode": "REPLAY"}
    if LADDER.index(to) <= LADDER.index(SYS.modes.mode): SYS.modes.mode = to
    else:
        stats, approval = _promotion_evidence(to)
        g = gate(SYS.modes.mode, to, stats, approval)
        reasons = list(g.reasons)
        if g.allowed and LADDER.index(to) > LADDER.index(Mode.PAPER):
            readiness = execution_status("binance")
            if not readiness["order_submission_available"]:
                reasons.append("venue execution client is not configured")
        if not reasons and g.allowed:
            SYS.modes.mode = to
        else:
            SYS.store.audit(r.value, "mode_rejected", f"{to.value}: gate denied: {'; '.join(reasons)}")
            raise HTTPException(403, {"gate_reasons": reasons})
    SYS.store.audit(r.value, "mode", to.value); return {"mode": SYS.modes.mode.value}
class KillIn(BaseModel): reason: str = "manual kill"
@app.post("/api/kill")
def kill(body: KillIn, authorization: str | None = H):
    r = auth(authorization,"kill"); SYS.engage_kill(body.reason, r.value)
    return {"engaged": True, "desks_halted": sorted(SYS.kill.desks_halted)}
@app.post("/api/kill/reset")
def reset_kill(authorization: str | None = H, x_totp: str | None = TOTP):
    r = auth(authorization,"approve", x_totp)
    if not SYS.kill.engaged: raise HTTPException(409, "kill switch is not engaged")
    try: approval = Approval("kill:reset", r.value, "APPROVE").signed()
    except Exception as e: raise HTTPException(503, f"cannot sign owner reset: {e}")
    if not SYS.reset_kill(approval, r.value): raise HTTPException(403, "signed owner reset rejected")
    SYS.approvals.append({"subject":approval.subject,"approver":approval.approver,"decision":approval.decision,
                          "ts":approval.ts,"signature":approval.signature,"verified":approval.verify()})
    return {"engaged": False, "reset_by": r.value, "approval_verified": approval.verify()}
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
            frm, to = body.subject[8:].split("->")
            stats = getattr(SYS, "mode_stats", Stats())
            if not isinstance(stats, Stats):
                stats = Stats()
            g = gate(Mode(frm), Mode(to), stats, a)
            rec["gate_result"] = {"allowed": g.allowed, "reasons": list(g.reasons)}
        except ValueError: raise HTTPException(400, "bad promote subject")
    SYS.approvals.append(rec); SYS.store.audit(r.value, "approval", f"{a.subject} {a.decision}"); return rec
@app.get("/api/audit")
def audit(authorization: str | None = H): auth(authorization,"view"); return [list(r) for r in SYS.store.rows("audit_log")]

def _backtests():
    latest = ROOT/"reports"/"backtests-latest.json"
    example = ROOT/"reports"/"examples"/"backtests-walkforward-example.json"
    for p in (latest, example):
        if not p.exists(): continue
        data = json.loads(p.read_text())
        # Old-format full-sample reports are not shown as current walk-forward results.
        if data.get("variants") and all("folds" in v for v in data["variants"]): return data
    return {"label": "no walk-forward backtest run yet", "variants": [], "variants_tried": 0, "fold_runs": 0}
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
                   "india": lambda: {"gate0": D5.get("gate0"), "sebi": D5.get("sebi")}, "backtests": _backtests}, MEM, ROUTER, LLMBudget())
    return JEV
class JevIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000); save_note: bool = False
@app.post("/api/jev")
def jev(body: JevIn, authorization: str | None = H):
    """view: ask (advisory text). save_note additionally needs jev_note (operator/owner); refused with 403 before any LLM call."""
    r = auth(authorization,"jev_note" if body.save_note else "view")
    rep = _jev().ask(body.question, body.save_note, role=r.value, may_persist=body.save_note)
    SYS.store.audit(r.value, "jev_note" if body.save_note and rep.status == "OK" else "jev_ask", rep.status); return jd(rep.__dict__)
class TAIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=15); source: str = "fixture"
@app.post("/api/research/ta")
def research_ta(body: TAIn, authorization: str | None = H):
    """Optional TA research desk (CREW_RESEARCH_TA=1): LLM research text only, operator/owner, budget-limited."""
    from . import research_ta as rta
    r = auth(authorization, "research")
    if not rta.enabled(): raise HTTPException(403, "TA research desk is off (CREW_RESEARCH_TA=1 to enable)")
    try: res = rta.ResearchDesk(ROUTER, _jev()._budget, MEM).run(body.symbol, r.value, body.source)
    except (rta.Disabled, PermissionError) as e: raise HTTPException(403, str(e))
    except ValueError as e: raise HTTPException(400, str(e))
    SYS.store.audit(r.value, "research_ta", f"{body.symbol} {body.source} {res.status}"); return jd(res.__dict__)
@app.get("/api/jev/budget")
def jev_budget(authorization: str | None = H): auth(authorization,"view"); return _jev()._budget.status()

@app.websocket("/ws/{channel}")
async def ws(sock: WebSocket, channel: str):
    """First-message auth: client must send {"auth": "<token>"} within 5 s. Tokens are never accepted in the URL."""
    await sock.accept()
    try:
        msg = await asyncio.wait_for(sock.receive_json(), 5)
        role = role_of(msg.get("auth") if isinstance(msg, dict) else None)
        require(role, "view")
        if channel not in {"summary", "agents", "trace", "pnl", "market_data"}:
            await sock.close(code=4404); return
    except Exception:
        await sock.close(code=4401); return
    try:
        while True:
            if channel == "market_data": payload = LIVE_FEED.snapshot() if LIVE_FEED else {"status": "DISABLED", "last_error": LIVE_FEED_ERROR}
            elif channel == "agents": payload = [a.metrics() for a in SYS.reg.all()]
            elif channel == "trace": payload = [dict(zip(TC, r)) for r in SYS.store.rows("trace")[-30:]]
            else: payload = snap()
            await sock.send_json({"channel": channel, "data": jd(payload)}); await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError): pass

app.mount("/static", StaticFiles(directory=ROOT/"web"), name="static")
@app.get("/")
def index(): return FileResponse(ROOT/"web"/"index.html")
