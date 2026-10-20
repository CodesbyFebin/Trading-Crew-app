"""Trading-skills catalog: deterministic, pure Python tools (Decimal math, no I/O, no network, no LLM).
Agents call them via REGISTRY[name](**kwargs). They compute; they never place orders or change risk state."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal as D, ROUND_DOWN
from typing import Callable
from .desk_d4 import book_walk
from .desks_synthetic import brier as _brier

def _d(x): return x if isinstance(x, D) else D(str(x))
def sma(prices, n: int):
    p = [_d(x) for x in prices]; return [None if i+1 < n else sum(p[i+1-n:i+1], D(0))/n for i in range(len(p))]
def ema(prices, n: int):
    a, out, e = D(2)/(n+1), [], None
    for x in map(_d, prices): e = x if e is None else e + a*(x-e); out.append(e)
    return out
def rsi(prices, n: int = 14):
    """Wilder RSI. Returns None until n changes are available."""
    p = [_d(x) for x in prices]; out = [None]*len(p); g = l = D(0)
    for i in range(1, len(p)):
        ch = p[i]-p[i-1]; up, dn = max(ch, D(0)), max(-ch, D(0))
        if i <= n: g += up; l += dn
        if i == n: g, l = g/n, l/n
        elif i > n: g, l = (g*(n-1)+up)/n, (l*(n-1)+dn)/n
        if i >= n: out[i] = D(100) if l == 0 else D(100) - D(100)/(1+g/l)
    return out
def atr(high, low, close, n: int = 14):
    h, l, c = [list(map(_d, x)) for x in (high, low, close)]
    tr = [h[0]-l[0]] + [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(c))]
    return sma(tr, n)
def realized_vol(prices):
    p = [_d(x) for x in prices]; r = [p[i]/p[i-1]-1 for i in range(1, len(p))]
    if len(r) < 2: return None
    mu = sum(r, D(0))/len(r); return (sum(((x-mu)**2 for x in r), D(0))/(len(r)-1)).sqrt()
def max_drawdown(equity):
    peak, mdd = None, D(0)
    for x in map(_d, equity):
        peak = x if peak is None or x > peak else peak; mdd = max(mdd, (peak-x)/peak if peak else D(0))
    return mdd
def position_size(equity, entry, stop, risk_frac="0.01", lot_step="1"):
    """Units such that (entry-stop)*units <= equity*risk_frac, rounded DOWN to lot_step. Fails closed on bad input."""
    e, en, st, rf, ls = map(_d, (equity, entry, stop, risk_frac, lot_step))
    if min(e, en, ls) <= 0 or not (D(0) < rf < D(1)) or st >= en: return D(0)
    return ((e*rf/(en-st)) / ls).to_integral_value(ROUND_DOWN) * ls
def kelly_fraction(p_win, payoff, cap="0.25"):
    p, b, c = map(_d, (p_win, payoff, cap)); f = p - (1-p)/b if b > 0 else D(0)
    return max(D(0), min(f, c))
def fee_slippage(levels, qty, fee_rate="0.001"):
    """Walk the book (list of [price, qty]); returns avg px, slippage bps vs best, fee, total cost. Raises on thin book."""
    lv = [(_d(p), _d(q)) for p, q in levels]; q = _d(qty); px = book_walk(lv, q)
    notional = px*q; fee = notional*_d(fee_rate)
    return {"avg_px": px, "slippage_bps_vs_best": abs(px-lv[0][0])/lv[0][0]*10000, "fee": fee, "notional": notional, "total_cost": notional+fee}
def round_to_step(qty, step):
    s = _d(step); return (_d(qty)/s).to_integral_value(ROUND_DOWN)*s if s > 0 else D(0)
def dust_after_rounding(qty, step):
    return _d(qty) - round_to_step(qty, step)
def brier(probs, outcomes): return _brier(probs, outcomes)
def reconcile(start_cash, ledger, engine_cash):
    """ledger: list of (amount, fee). Returns ledger cash and drift vs engine (must be 0)."""
    lc = _d(start_cash) + sum((_d(a)-_d(f) for a, f in ledger), D(0)); return {"ledger_cash": lc, "drift": lc - _d(engine_cash)}
def india_entry_window(iso_ts: str):
    from .desk_d5 import timing; return timing(datetime.fromisoformat(iso_ts))
def india_order_rate(order_ts):
    from .desk_d5 import order_rate_check; return order_rate_check([float(x) for x in order_ts])

@dataclass(frozen=True)
class Skill:
    name: str; category: str; fn: Callable; signature: str; doc: str
    def __call__(self, **kw): return self.fn(**kw)

REGISTRY = {s.name: s for s in [
 Skill("sma","indicator",sma,"prices, n","simple moving average"),
 Skill("ema","indicator",ema,"prices, n","exponential moving average"),
 Skill("rsi","indicator",rsi,"prices, n=14","Wilder RSI"),
 Skill("atr","indicator",atr,"high, low, close, n=14","average true range (SMA of TR)"),
 Skill("realized_vol","risk-metric",realized_vol,"prices","sample stdev of simple returns"),
 Skill("max_drawdown","risk-metric",max_drawdown,"equity","peak-to-trough fraction"),
 Skill("position_size","sizing",position_size,"equity, entry, stop, risk_frac=0.01, lot_step=1","fixed-fractional risk sizing, rounded down"),
 Skill("kelly_fraction","sizing",kelly_fraction,"p_win, payoff, cap=0.25","capped Kelly fraction (never negative)"),
 Skill("fee_slippage","costs",fee_slippage,"levels, qty, fee_rate=0.001","book-walk fill cost; fee_rate is an assumption to verify"),
 Skill("round_to_step","exchange",round_to_step,"qty, step","round qty down to lot step"),
 Skill("dust_after_rounding","exchange",dust_after_rounding,"qty, step","residual dust after lot-step rounding"),
 Skill("brier","calibration",brier,"probs, outcomes","Brier score"),
 Skill("reconcile","accounting",reconcile,"start_cash, ledger, engine_cash","ledger vs engine cash drift"),
 Skill("india_entry_window","calendar",india_entry_window,"iso_ts","D5 IST entry/square-off window check (no blackout calendar exists -> entries still blocked elsewhere)"),
 Skill("india_order_rate","compliance",india_order_rate,"order_ts","peak orders/sec vs ASSUMED 10/s SEBI threshold"),
]}
def catalog(): return [{"name": s.name, "category": s.category, "signature": s.signature, "doc": s.doc} for s in REGISTRY.values()]
