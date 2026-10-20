"""Desks D1 (prediction markets), D2 (equities night research), D3 (memecoin scanner).
SYNTHETIC FIXTURES ONLY. NOT_APPROVED_BY_OWNER. Locked to REPLAY; cannot be promoted."""
from __future__ import annotations
import json, random
from dataclasses import dataclass
from decimal import Decimal as D
from pathlib import Path
from .modes import Mode

LABEL = "SYNTHETIC FIXTURE - not real data"
FIX = Path(__file__).resolve().parent.parent / "fixtures"

class DeskLocked(Exception): pass
@dataclass
class LockedDesk:
    desk: str; name: str; status: str = "NOT_APPROVED_BY_OWNER"; mode: Mode = Mode.REPLAY
    def set_mode(self, m: Mode):
        if m is not Mode.REPLAY: raise DeskLocked(f"{self.desk} {self.status}: cannot leave REPLAY")

DESKS = {"D1": LockedDesk("D1","Polymarket prediction desk"), "D2": LockedDesk("D2","Equities night research"),
         "D3": LockedDesk("D3","Memecoin scanner")}

def load(name): return json.loads((FIX/name).read_text())

# D1: S03 -> S12 -> S13 -> S28 (REPLAY, no orders; produces paper "would-trade" list)
def s12_montecarlo(spot: D, strike: D, vol: D, steps: int, n=5000, seed=7) -> D:
    rng = random.Random(seed); s0, v = float(spot), float(vol); hits = 0
    for _ in range(n):
        x = s0
        for _ in range(steps): x *= 1 + rng.gauss(0, v)
        hits += x > float(strike)
    return D(hits)/D(n)

def s13_fair_value(p_up: D, ask: D, fee=D("0.02")) -> D: return p_up - ask - fee

def run_d1():
    mk = load("d1_prediction_markets.json"); out = []
    for m in mk["markets"]:
        p = s12_montecarlo(D(m["spot"]), D(m["strike"]), D(m["vol_per_step"]), m["steps_left"])
        edge = s13_fair_value(p, D(m["yes_ask"]))
        out.append({"market": m["id"], "p_up": str(p), "yes_ask": m["yes_ask"], "edge_after_fees": str(edge),
                    "would_trade_in_replay": edge > D("0.03"), "label": LABEL})
    return out

def brier(probs, outcomes) -> D:
    return sum(((D(p)-D(o))**2 for p,o in zip(probs,outcomes)), D(0))/len(probs)

# D2: S06 -> S19 / S20 deterministic rules
RED = ("going concern", "auditor change", "restatement")
def run_d2():
    f = load("d2_filings.json"); out = []
    for x in f["filings"]:
        flags = [r for r in RED if r in x["text"].lower()]
        cluster = x.get("insider_buys_30d", 0) >= 3
        out.append({"ticker": x["ticker"], "form": x["form"], "red_flags": flags, "insider_cluster_buy": cluster,
                    "watch": cluster and not flags, "label": LABEL})
    return out

# D3: S05 -> S23 / S24 PASS/DROP filters
FILTERS = [("min_liquidity", lambda t: t["liquidity_usd"] >= 50000), ("age_hours", lambda t: t["age_hours"] >= 24),
           ("deployer_prior_rugs", lambda t: t["deployer_prior_rugs"] == 0), ("top10_holders_pct", lambda t: t["top10_pct"] < 40),
           ("mint_authority_revoked", lambda t: t["mint_revoked"])]
def run_d3():
    out = []
    for t in load("d3_tokens.json")["tokens"]:
        res = [(n, bool(f(t))) for n, f in FILTERS]
        out.append({"symbol": t["symbol"], "filters": res, "verdict": "PASS" if all(v for _,v in res) else "DROP", "label": LABEL})
    return out
