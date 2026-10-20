"""Desk D4: crypto signals on the Binance replay sample (synthetic sample prices, not real market data)."""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal as D, ROUND_DOWN
from pathlib import Path

FEE_RATE = D("0.001")   # assumed 10 bps taker fee model parameter (Binance spot base tier); verify before any live use
@dataclass(frozen=True)
class Tick:
    ts: int; symbol: str; bid: D; ask: D; bids: tuple; asks: tuple; qv24: D; status: str
    @property
    def mid(self): return (self.bid+self.ask)/2

@dataclass(frozen=True)
class QAReport:
    ticks: tuple; input_rows: int; duplicates: int; crossed: int; non_trading: int; gaps: int; out_of_order: int

@dataclass(frozen=True)
class Feat:
    ts: int; symbol: str; mid: D; ema_f: D; ema_s: D; spread_bps: D; imbalance: D; vol: D; slope: D

@dataclass(frozen=True)
class Fill:
    ticket_id: str; ts: int; symbol: str; side: str; qty: D; avg_px: D; notional: D; fee: D; slippage_bps: D

def s01_tape(path: Path) -> list[Tick]:
    out = []
    for line in Path(path).read_text().splitlines():
        d = json.loads(line)
        if d.get("type") != "market": continue
        out.append(Tick(int(d["ts"]), d["symbol"], D(str(d["bid"])), D(str(d["ask"])),
            tuple((D(str(p)),D(str(q))) for p,q in d["bids"]), tuple((D(str(p)),D(str(q))) for p,q in d["asks"]),
            D(str(d["quote_volume_24h"])), d["status"]))
    return out

def s09_dataqa(ticks: list[Tick]) -> QAReport:
    seen, keep, dup, crossed, nt, gaps, ooo, last = set(), [], 0, 0, 0, 0, 0, {}
    for t in ticks:
        k = (t.symbol, t.ts)
        if k in seen: dup += 1; continue
        seen.add(k)
        if t.bid >= t.ask: crossed += 1; continue
        if t.status != "TRADING": nt += 1; continue
        p = last.get(t.symbol)
        if p is not None:
            if t.ts <= p: ooo += 1; continue
            if t.ts - p > 60: gaps += 1
        last[t.symbol] = t.ts; keep.append(t)
    return QAReport(tuple(keep), len(ticks), dup, crossed, nt, gaps, ooo)

def _ema(prev, x, n): a = D(2)/(n+1); return x if prev is None else prev + a*(x-prev)

def s10_features(ticks, fast=20, slow=60, vol_n=60) -> list[Feat]:
    out, st = [], {}
    for t in ticks:
        s = st.setdefault(t.symbol, {"f":None,"s":None,"hist":[],"slow_hist":[]})
        m = t.mid; s["f"] = _ema(s["f"], m, fast); s["s"] = _ema(s["s"], m, slow)
        h = s["hist"]; h.append(m); h[:] = h[-(vol_n+1):]
        rets = [(h[i]/h[i-1]-1) for i in range(1,len(h))]
        mu = sum(rets, D(0))/len(rets) if rets else D(0)
        vol = (sum(((r-mu)**2 for r in rets), D(0))/len(rets)).sqrt() if rets else D(0)
        sh = s["slow_hist"]; sh.append(s["s"]); sh[:] = sh[-31:]
        slope = (sh[-1]/sh[0]-1) if len(sh) > 30 else D(0)
        bq = sum((q for _,q in t.bids), D(0)); aq = sum((q for _,q in t.asks), D(0))
        out.append(Feat(t.ts, t.symbol, m, s["f"], s["s"], (t.ask-t.bid)/m*10000, (bq-aq)/(bq+aq), vol, slope))
    return out

def s14_regime(f: Feat) -> str:
    if f.slope > D("0.0001"): return "TREND_UP"
    if f.slope < D("-0.0001"): return "TREND_DOWN"
    return "CHOP"

def s27_size(equity: D, frac=D("0.015")) -> D:
    return (equity*frac).quantize(D("0.01"), rounding=ROUND_DOWN)

def book_walk(levels, qty):
    rem, cost = qty, D(0)
    for p,q in levels:
        take = min(rem, q); cost += take*p; rem -= take
        if rem <= 0: break
    if rem > 0: raise ValueError("insufficient book depth")
    return cost/qty

def s36_paper_fill(tid, tick: Tick, side: str, notional=None, qty=None) -> Fill:
    if side == "BUY":
        q = (notional/tick.ask).quantize(D("0.00001"), rounding=ROUND_DOWN); px = book_walk(tick.asks, q)
    else:
        q = qty; px = book_walk(tick.bids, q)
    n = (q*px); slip = abs(px-tick.mid)/tick.mid*10000
    return Fill(tid, tick.ts, tick.symbol, side, q, px, n, (n*FEE_RATE).quantize(D("0.00000001")), slip)

def day_of(ts): return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
