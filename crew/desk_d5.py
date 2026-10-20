"""Desk D5: India NSE equities. ARCHIVED_RESEARCH_ONLY / NOT_APPROVED_BY_OWNER.
Isolated: no imports from other desks, no cross-track signals. Reuses /workspace/indiatrader READ-ONLY
(imported with bytecode writing disabled so nothing is written into that tree). No strategy is run:
all prior candidates were rejected; restart needs a new strategy + explicit owner approval.
Replay here exercises risk / universe / timing / calendar checks only, with labelled probe intents."""
from __future__ import annotations
import csv, io, os, re, sys, zipfile
from dataclasses import dataclass
from datetime import datetime, date, time as dtime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

INDIA_ROOT = Path(os.environ.get("INDIATRADER_ROOT", "/workspace/indiatrader"))
IST = timezone(timedelta(hours=5, minutes=30))
STATUS = "ARCHIVED_RESEARCH_ONLY / NOT_APPROVED_BY_OWNER"

def _import():
    sys.dont_write_bytecode = True
    if str(INDIA_ROOT) not in sys.path: sys.path.insert(0, str(INDIA_ROOT))
    from indiatrader import risk, calendar, universe, costs, models, instruments
    return risk, calendar, universe, costs, models, instruments

# ---- Gate 0 terms (locked 2026-10-20; mirrored from indiatrader, checked against its LIMITS in tests) ----
GATE0 = {"broker": "Fyers", "product": "CNC long-only", "rejected_products": ["MIS","MTF","NRML","BO","CO"],
         "risk_per_trade": "0.01", "single_stock_cap": "0.10 (exactly 10% = breach)", "daily_loss": "0.02",
         "weekly_loss": "0.03", "max_drawdown": "0.06", "entry_cutoff_ist": "15:00", "square_off_ist": "15:20",
         "disable_ist": "15:25", "blackout": "versioned calendar incl. full-day RBI", "numbers": "Decimal only",
         "vps": "planned, not bought"}
ENTRY_START, ENTRY_END, SQUARE_OFF, DISABLE = dtime(9,15), dtime(15,0), dtime(15,20), dtime(15,25)

def timing(now: datetime) -> dict:
    if now.tzinfo is None: return {"entries": False, "square_off": True, "disabled": True, "reason": "NAIVE_CLOCK"}
    t = now.astimezone(IST).time()
    return {"entries": ENTRY_START <= t < ENTRY_END, "square_off": t >= SQUARE_OFF, "disabled": t >= DISABLE,
            "reason": "OK" if ENTRY_START <= t < ENTRY_END else "OUTSIDE_WINDOW"}

# ---- SEBI retail-algo compliance gates: hard checks; any failure blocks everything past REPLAY ----
ORDER_RATE_THRESHOLD_OPS = D("10")      # orders/sec registration threshold; ASSUMPTION - verify against current SEBI/NSE circulars and Fyers
ORDER_RATE_WARN_FRACTION = D("0.8")

@dataclass(frozen=True)
class OwnerSignals:
    algo_id_confirmed: bool = False      # owner must send exactly 'ALGO-ID CONFIRMED'
    static_ip_whitelisted: bool = False  # owner must send exactly 'VPS IP WHITELISTED'
    signed_owner_approval: bool = False  # HMAC-signed approval (2FA stand-in)
    audit_trail_ok: bool = False

def parse_owner_signal(text: str, sig: OwnerSignals) -> OwnerSignals:
    t = text.strip()
    if t == "ALGO-ID CONFIRMED": return OwnerSignals(True, sig.static_ip_whitelisted, sig.signed_owner_approval, sig.audit_trail_ok)
    if t == "VPS IP WHITELISTED": return OwnerSignals(sig.algo_id_confirmed, True, sig.signed_owner_approval, sig.audit_trail_ok)
    return sig

def order_rate_check(order_ts: list[float]) -> dict:
    peak = 0
    for i, t in enumerate(order_ts):
        n = sum(1 for x in order_ts[i:] if x - t < 1.0); peak = max(peak, n)
    pk = D(peak)
    return {"peak_orders_per_sec": peak, "threshold": str(ORDER_RATE_THRESHOLD_OPS),
            "flag": pk >= ORDER_RATE_THRESHOLD_OPS * ORDER_RATE_WARN_FRACTION, "breach": pk >= ORDER_RATE_THRESHOLD_OPS}

def sebi_gates(sig: OwnerSignals, order_ts=(), strategy_approved=False) -> dict:
    rate = order_rate_check(list(order_ts))
    items = [("strategy", strategy_approved, "new strategy + explicit owner approval (all prior candidates rejected)"),
             ("algo_id", sig.algo_id_confirmed, "broker algo-ID confirmed (owner signal 'ALGO-ID CONFIRMED')"),
             ("static_ip", sig.static_ip_whitelisted, "static IP whitelisted (owner signal 'VPS IP WHITELISTED'); VPS not bought"),
             ("order_rate", not rate["flag"], f"order rate below {ORDER_RATE_WARN_FRACTION*100}% of {ORDER_RATE_THRESHOLD_OPS}/s threshold"),
             ("owner_2fa", sig.signed_owner_approval, "signed owner approval / 2FA"),
             ("audit_trail", sig.audit_trail_ok, "append-only audit trail verified"),
             ("live_enabled", False, "LIVE_ENABLED=false and Fyers keys absent in this build")]
    return {"checklist": [{"gate": g, "ok": ok, "detail": d} for g, ok, d in items], "order_rate": rate,
            "may_leave_replay": all(ok for _, ok, _ in items)}

def can_leave_replay(**k) -> bool: return sebi_gates(**k)["may_leave_replay"]

# ---- replay of risk/universe/timing checks over local bhavcopy (no strategy) ----
def _bhav_dates():
    out = []
    for p in sorted((INDIA_ROOT/"data"/"raw"/"bhavcopy").glob("BhavCopy_NSE_CM_*.csv.zip")):
        m = re.search(r"_(\d{8})_F_", p.name)
        if m: out.append((date(int(m[1][:4]),int(m[1][4:6]),int(m[1][6:])), p))
    return out

def _close(path: Path, isin: str):
    with zipfile.ZipFile(path) as z:
        rows = csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0])))
        for r in rows:
            if r.get("ISIN") == isin and r.get("SctySrs") == "EQ": return D(r["ClsPric"])
    return None

def replay(max_days: int | None = None, probe_every: int = 25) -> dict:
    risk, cal, U, costs, M, I = _import()
    RA = risk.RiskAuthorityIN()
    dates = _bhav_dates()[:max_days] if max_days else _bhav_dates()
    universe_ok = universe_fail = 0; fails = []; probes = []
    calendar = None   # no production versioned calendar exists in indiatrader -> entries must fail closed
    for i, (d, p) in enumerate(dates):
        try:
            mem = U.member_isins(d); U.check_count(d); universe_ok += 1
        except Exception as e:
            universe_fail += 1; fails.append({"date": d.isoformat(), "error": f"{type(e).__name__}: {e}"}); continue
        if i % probe_every: continue
        isin = sorted(mem)[0]; px = _close(p, isin)
        if px is None: continue
        st = M.AccountState(D(100000), D(100000), D(100000), D(100000), 0, 0, False, False)
        qty, why = RA.size(D(100000), px, px*D("0.99"), lambda q: costs.round_trip(q, px, px))
        res = {"date": d.isoformat(), "isin": isin, "close": str(px), "size": [qty, why]}
        for label, mins, prod in (("10:00 CNC", 600, "CNC"), ("14:59 CNC", 899, "CNC"), ("15:00 CNC", 900, "CNC"), ("10:00 MIS", 600, "MIS")):
            o = M.OrderIntent(f"probe-{d}-{label}", "probe", "BUY", max(qty,1), px, px*D("0.99"), px*D("1.03"), prod, D(1),
                              costs.round_trip(max(qty,1), px, px), mins, isin, d)
            res[label] = RA.check(o, st).reason
        cs = cal.entry_status(calendar, datetime.combine(d, dtime(10,0), IST))
        res["calendar_entry"] = cs.reason
        probes.append(res)
    pre = U.member_isins  # fail-closed check before universe start
    try: pre(date(2024,3,1)); pre_res = "NOT FAIL-CLOSED"
    except Exception as e: pre_res = f"fail-closed: {type(e).__name__}"
    return {"status": STATUS, "label": "risk/universe/timing replay only - probe intents, NOT a strategy, no PnL",
            "sessions": len(dates), "first": dates[0][0].isoformat() if dates else None, "last": dates[-1][0].isoformat() if dates else None,
            "universe_ok": universe_ok, "universe_fail": universe_fail, "universe_failures": fails[:20],
            "pre_universe_date": pre_res, "probes": probes, "probe_count": len(probes),
            "production_calendar": "absent -> entries blocked (CALENDAR_MISSING)"}
