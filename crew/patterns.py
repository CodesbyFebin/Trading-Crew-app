"""Candlestick pattern detectors (research-only, deterministic, Decimal, no I/O).
Clean-room implementation of textbook definitions. The pattern list was inspired by the candlestick skill in
HKUDS/Vibe-Trading (MIT; see third_party/HKUDS_Vibe-Trading/NOTICE.md); no code was copied.
Output is a list of pattern NAMES per bar. There is deliberately no long/short score or signal: these labels are
research annotations and are not wired into the engine, risk engine or order path.
No lookahead: the label at bar i uses only bars <= i (tests prove prefix invariance)."""
from __future__ import annotations
from decimal import Decimal as D

def _d(x): return x if isinstance(x, D) else D(str(x))

def _bar(o, h, l, c):
    o, h, l, c = map(_d, (o, h, l, c))
    if not all(v.is_finite() and v > 0 for v in (o, h, l, c)) or h < max(o, c) or l > min(o, c):
        raise ValueError("invalid OHLC bar")
    return o, h, l, c

def detect(open_, high, low, close, doji_body_pct="0.1", shadow_ratio="2", trend_n: int = 3) -> list[list[str]]:
    if not (len(open_) == len(high) == len(low) == len(close)): raise ValueError("OHLC lengths differ")
    bars = [_bar(*x) for x in zip(open_, high, low, close)]
    dp, sr = _d(doji_body_pct), _d(shadow_ratio); out = []
    for i, (o, h, l, c) in enumerate(bars):
        rng = h - l; body = abs(c - o); up = h - max(o, c); lo = min(o, c) - l; p = []
        down_trend = i >= trend_n and all(bars[j][3] < bars[j - 1][3] for j in range(i - trend_n + 1, i))
        up_trend = i >= trend_n and all(bars[j][3] > bars[j - 1][3] for j in range(i - trend_n + 1, i))
        if rng > 0 and body <= dp * rng: p.append("doji")
        if body > 0 and lo >= sr * body and up <= body and down_trend: p.append("hammer")
        if body > 0 and up >= sr * body and lo <= body and up_trend: p.append("shooting_star")
        if i >= 1:
            po, ph, pl, pc = bars[i - 1]
            if pc < po and c > o and o <= pc and c >= po and body > abs(pc - po): p.append("bullish_engulfing")
            if pc > po and c < o and o >= pc and c <= po and body > abs(pc - po): p.append("bearish_engulfing")
            if pc < po and c > o and max(o, c) < po and min(o, c) > pc: p.append("bullish_harami")
            if pc > po and c < o and max(o, c) < pc and min(o, c) > po: p.append("bearish_harami")
        if i >= 2:
            (ao, _, _, ac), (bo, _, _, bc) = bars[i - 2][0:4], bars[i - 1][0:4]
            if ac < ao and abs(bc - bo) < abs(ac - ao) / 2 and c > o and c > (ao + ac) / 2: p.append("morning_star")
            if ac > ao and abs(bc - bo) < abs(ac - ao) / 2 and c < o and c < (ao + ac) / 2: p.append("evening_star")
            three = bars[i - 2:i + 1]
            if all(x[3] > x[0] for x in three) and three[0][3] < three[1][3] < three[2][3]: p.append("three_white_soldiers")
            if all(x[3] < x[0] for x in three) and three[0][3] > three[1][3] > three[2][3]: p.append("three_black_crows")
        out.append(p)
    return out
