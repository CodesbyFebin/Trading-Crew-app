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

# ---------------------------------------------------------------------------------------------
# RESEARCH-ONLY formulas (S63-S72 batch). Written from the published formulas, not copied from any
# upstream project's source. They are flagged research_only in the registry: no agent calls them,
# nothing in the engine or paper-day report uses them, and they never place orders or touch risk state.
# Ported from an untrusted bundle and reviewed: AMM sizing, Avellaneda-Stoikov spread, queue fill and
# webhook freshness were corrected (see tests/test_research_skills.py for hand-checked values).
# ---------------------------------------------------------------------------------------------
def freqtrade_roi_trailing(entry_px, current_px, peak_px, age_bars: int, roi_bps="150", trailing_bps="50", offset_bps="80"):
    """ROI target that decays linearly to 25% over 120 bars, plus a trailing stop armed once the peak is offset_bps above entry."""
    en, cur, pk, rb, tb, ob = map(_d, (entry_px, current_px, peak_px, roi_bps, trailing_bps, offset_bps))
    if min(en, cur, pk) <= 0 or pk < cur or int(age_bars) < 0: raise ValueError("invalid prices/age for ROI/trailing check")
    pnl_bps = (cur - en) / en * 10000; peak_bps = (pk - en) / en * 10000
    target = rb * max(D("0.25"), D(1) - D(int(age_bars)) / D(120))
    roi_hit = pnl_bps >= target; armed = peak_bps >= ob
    stop_px = pk * (D(1) - tb / D(10000)) if armed else None
    trail_hit = armed and cur <= stop_px
    return {"pnl_bps": pnl_bps, "target_roi_bps": target, "trail_armed": armed, "trail_stop_px": stop_px,
            "should_exit": bool(roi_hit or trail_hit), "exit_reason": "ROI_TABLE" if roi_hit else ("TRAILING_STOP" if trail_hit else "HOLD")}

def avellaneda_stoikov_mm(mid_price, inventory, sigma, gamma="0.1", horizon="1", kappa="1.5"):
    """Avellaneda-Stoikov (2008): reservation r = s - q*gamma*sigma^2*T; total spread = gamma*sigma^2*T + (2/gamma)*ln(1+gamma/kappa).
    sigma is in PRICE units per sqrt(time unit of T); kappa is order-arrival decay in 1/price units."""
    s, q, sig, gam, T, k = map(_d, (mid_price, inventory, sigma, gamma, horizon, kappa))
    if s <= 0 or sig < 0 or gam <= 0 or T <= 0 or k <= 0: raise ValueError("invalid Avellaneda-Stoikov parameters")
    r = s - q * gam * sig ** 2 * T
    spread = gam * sig ** 2 * T + (D(2) / gam) * (D(1) + gam / k).ln()
    return {"reservation_px": r, "bid_px": r - spread / 2, "ask_px": r + spread / 2, "spread": spread, "spread_bps": spread / s * 10000}

def queue_fill_estimate(queue_ahead_qty, traded_vol, cancel_frac="0", order_qty="1"):
    """FIFO queue depletion: volume that traded at our level plus cancels (cancel_frac of the queue ahead) removes
    the queue ahead first, then fills our order. Deterministic fraction filled, not a probability model."""
    qa, tv, cf, oq = map(_d, (queue_ahead_qty, traded_vol, cancel_frac, order_qty))
    if qa < 0 or tv < 0 or not (D(0) <= cf <= D(1)) or oq <= 0: raise ValueError("invalid queue parameters")
    depl = tv + qa * cf
    filled = min(oq, max(D(0), depl - qa))
    return {"remaining_queue_ahead": max(D(0), qa - depl), "filled_qty": filled, "fill_fraction": filled / oq}

def grid_dca_ladder(center_price, span_pct="0.04", levels: int = 4, scale_mult="1"):
    """Evenly spaced buy/sell rungs within +/- span_pct; rung weights proportional to scale_mult**i (scale_mult>1 is
    martingale-style size escalation, research only)."""
    cp, sp, sm = map(_d, (center_price, span_pct, scale_mult)); lv = int(levels)
    if cp <= 0 or not (D(0) < sp < D(1)) or lv < 1 or sm <= 0: raise ValueError("invalid grid parameters")
    step = sp / lv; raw = [sm ** i for i in range(lv)]; tot = sum(raw, D(0))
    w = [x / tot for x in raw]
    return {"buy": [{"level": i+1, "price": cp * (1 - step*(i+1)), "weight": w[i]} for i in range(lv)],
            "sell": [{"level": i+1, "price": cp * (1 + step*(i+1)), "weight": w[i]} for i in range(lv)]}

def amm_optimal_arb_size(reserve_a1, reserve_b1, reserve_b2, reserve_a2, fee_bps="30"):
    """Two constant-product pools: sell A into pool 1 (A,B), sell the B into pool 2 (B,A). With g = 1 - fee,
    optimal input x* = (sqrt(g^2*a1*b1*b2*a2) - a1*b2) / (g*(b2 + g*b1)). Returns 0 when no profitable loop exists."""
    a1, b1, b2, a2, fb = map(_d, (reserve_a1, reserve_b1, reserve_b2, reserve_a2, fee_bps))
    if min(a1, b1, b2, a2) <= 0 or not (D(0) <= fb < D(10000)): raise ValueError("invalid AMM reserves/fee")
    g = D(1) - fb / D(10000)
    x = ((g*g*a1*b1*b2*a2).sqrt() - a1*b2) / (g*(b2 + g*b1))
    if x <= 0: return {"optimal_input_a": D(0), "output_a": D(0), "profit_a": D(0)}
    ob = b1*g*x / (a1 + g*x); oa = a2*g*ob / (b2 + g*ob)
    return {"optimal_input_a": x, "output_a": oa, "profit_a": oa - x}

def triangular_arb_edge(rate_ab, rate_bc, rate_ca, fee_bps="10"):
    """Loop A->B->C->A using conversion rates (units of next asset per unit of current). Net multiplier after 3 fees."""
    r1, r2, r3, fb = map(_d, (rate_ab, rate_bc, rate_ca, fee_bps))
    if min(r1, r2, r3) <= 0 or not (D(0) <= fb < D(10000)): raise ValueError("invalid triangular rates/fee")
    gross = r1*r2*r3; net = gross * (D(1) - fb/D(10000)) ** 3
    return {"gross_mult": gross, "net_mult": net, "net_edge_bps": (net - 1) * 10000}

def binary_complement_cost(yes_ask_a, no_ask_b, fee_per_contract_a="0", fee_per_contract_b="0"):
    """Buy YES on venue A and NO on venue B for the same event; payout is 1 per pair IF both venues resolve identically.
    edge = 1 - total cost. Resolution-rule mismatch, settlement and counterparty risk are NOT modelled, so a positive edge is not riskless."""
    ya, nb, fa, fb = map(_d, (yes_ask_a, no_ask_b, fee_per_contract_a, fee_per_contract_b))
    if not (D(0) < ya < D(1)) or not (D(0) < nb < D(1)) or fa < 0 or fb < 0: raise ValueError("prices must be in (0,1), fees >= 0")
    cost = ya + nb + fa + fb
    return {"pair_cost": cost, "edge_per_pair": D(1) - cost, "note": "not riskless: resolution-rule and venue risk unmodelled"}

def weighted_pillar_score(trend, mean_rev, momentum, volume, risk_scalar="1", weights=("0.30", "0.20", "0.25", "0.25")):
    """Weighted sum of four caller-supplied scores in [-1,1], times risk_scalar in [0,1]. Weights are arbitrary defaults,
    not calibrated. Returns a number only; no LONG/SHORT verdict."""
    xs = list(map(_d, (trend, mean_rev, momentum, volume))); rs = _d(risk_scalar); w = list(map(_d, weights))
    if len(w) != 4 or any(not (D(-1) <= x <= D(1)) for x in xs) or not (D(0) <= rs <= D(1)): raise ValueError("scores in [-1,1], risk_scalar in [0,1], 4 weights")
    return {"score": sum((a*b for a, b in zip(xs, w)), D(0)) * rs}

def bellman_q_update(q_current, reward, max_q_next, alpha="0.1", gamma="0.95"):
    """Tabular Q-learning update: Q <- Q + alpha*(r + gamma*maxQ' - Q)."""
    qc, r, qn, a, g = map(_d, (q_current, reward, max_q_next, alpha, gamma))
    if not (D(0) < a <= D(1)) or not (D(0) <= g <= D(1)): raise ValueError("invalid alpha/gamma")
    td = r + g*qn - qc
    return {"q_updated": qc + a*td, "td_error": td}

def validate_webhook_signal(payload: dict, now_ts: int, max_age_s: int = 60):
    """Fail-closed schema + freshness check for an inbound signal. now_ts is required (no self-referential clock)."""
    if not isinstance(payload, dict): return {"valid": False, "reason": "NOT_AN_OBJECT"}
    if not {"symbol", "side", "ts", "source"} <= payload.keys(): return {"valid": False, "reason": "MISSING_FIELDS"}
    sym, side = str(payload["symbol"]).strip(), str(payload["side"]).upper().strip()
    if not sym or side not in {"BUY", "SELL", "FLAT"}: return {"valid": False, "reason": "INVALID_SYMBOL_OR_SIDE"}
    try: ts, now, mx = int(payload["ts"]), int(now_ts), int(max_age_s)
    except (TypeError, ValueError): return {"valid": False, "reason": "BAD_TIMESTAMP"}
    if mx <= 0 or abs(now - ts) > mx: return {"valid": False, "reason": "STALE_OR_FUTURE"}
    return {"valid": True, "reason": "OK", "symbol": sym, "side": side}

@dataclass(frozen=True)
class Skill:
    name: str; category: str; fn: Callable; signature: str; doc: str; research_only: bool = False
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
RO = "RESEARCH ONLY - no agent, not in execution or reports. "
REGISTRY.update({s.name: s for s in [
 Skill("freqtrade_roi_trailing","research",freqtrade_roi_trailing,"entry_px, current_px, peak_px, age_bars, roi_bps=150, trailing_bps=50, offset_bps=80",RO+"decaying ROI target + trailing stop (ref: freqtrade docs)",True),
 Skill("avellaneda_stoikov_mm","research",avellaneda_stoikov_mm,"mid_price, inventory, sigma, gamma=0.1, horizon=1, kappa=1.5",RO+"Avellaneda-Stoikov reservation price and spread (ref: 2008 paper)",True),
 Skill("queue_fill_estimate","research",queue_fill_estimate,"queue_ahead_qty, traded_vol, cancel_frac=0, order_qty=1",RO+"FIFO queue depletion, fraction filled",True),
 Skill("grid_dca_ladder","research",grid_dca_ladder,"center_price, span_pct=0.04, levels=4, scale_mult=1",RO+"grid rungs; scale_mult>1 = martingale sizing",True),
 Skill("amm_optimal_arb_size","research",amm_optimal_arb_size,"reserve_a1, reserve_b1, reserve_b2, reserve_a2, fee_bps=30",RO+"closed-form 2-pool x*y=k arbitrage size",True),
 Skill("triangular_arb_edge","research",triangular_arb_edge,"rate_ab, rate_bc, rate_ca, fee_bps=10",RO+"3-leg loop net edge after fees",True),
 Skill("binary_complement_cost","research",binary_complement_cost,"yes_ask_a, no_ask_b, fee_per_contract_a=0, fee_per_contract_b=0",RO+"cross-venue YES+NO pair cost; not riskless",True),
 Skill("weighted_pillar_score","research",weighted_pillar_score,"trend, mean_rev, momentum, volume, risk_scalar=1, weights",RO+"uncalibrated weighted score, no verdict",True),
 Skill("bellman_q_update","research",bellman_q_update,"q_current, reward, max_q_next, alpha=0.1, gamma=0.95",RO+"tabular Q-learning update",True),
 Skill("validate_webhook_signal","research",validate_webhook_signal,"payload, now_ts, max_age_s=60",RO+"fail-closed signal schema/freshness check",True),
]})
from .patterns import detect as _candle_patterns
REGISTRY["candle_patterns"] = Skill("candle_patterns","research",_candle_patterns,"open_, high, low, close, doji_body_pct=0.1, shadow_ratio=2, trend_n=3",
                                    RO+"candlestick pattern NAMES per bar (no score/signal); idea from HKUDS/Vibe-Trading (MIT), clean-room",True)
def catalog(): return [{"name": s.name, "category": s.category, "signature": s.signature, "doc": s.doc, "research_only": s.research_only} for s in REGISTRY.values()]
