"""Offline L2 order book + feed-staleness / clock-drift guard. Works on replay fixtures only; no live feed is wired.
All prices and sizes are Decimal."""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal as D

class BookError(ValueError): pass

@dataclass(frozen=True)
class L2Book:
    symbol: str; ts: int
    bids: tuple[tuple[D, D], ...]   # best first (descending price)
    asks: tuple[tuple[D, D], ...]   # best first (ascending price)
    def __post_init__(self):
        if not self.bids or not self.asks: raise BookError("empty side")
        if any(q <= 0 or p <= 0 for p, q in self.bids + self.asks): raise BookError("non-positive level")
        if [p for p, _ in self.bids] != sorted((p for p, _ in self.bids), reverse=True): raise BookError("bids not descending")
        if [p for p, _ in self.asks] != sorted(p for p, _ in self.asks): raise BookError("asks not ascending")
        if self.bids[0][0] >= self.asks[0][0]: raise BookError("crossed book")
    @classmethod
    def from_row(cls, r: dict) -> "L2Book":
        f = lambda lv: tuple((D(str(p)), D(str(q))) for p, q in lv)
        return cls(r["symbol"], int(r["ts"]), f(r["bids"]), f(r["asks"]))
    @property
    def best_bid(self): return self.bids[0][0]
    @property
    def best_ask(self): return self.asks[0][0]
    @property
    def mid(self): return (self.best_bid + self.best_ask) / 2
    def spread_bps(self) -> D: return (self.best_ask - self.best_bid) / self.mid * 10000
    def depth(self, side: str, within_bps: D | None = None) -> D:
        """Total size on a side, optionally only levels within `within_bps` of mid."""
        lv = self.bids if side == "bid" else self.asks
        if within_bps is None: return sum((q for _, q in lv), D(0))
        lim = self.mid * within_bps / 10000
        return sum((q for p, q in lv if abs(p - self.mid) <= lim), D(0))
    def vwap_fill(self, side: str, qty: D) -> dict:
        """Estimated fill for a BUY (walks asks) or SELL (walks bids). Raises BookError if depth is insufficient."""
        qty = D(str(qty))
        if qty <= 0: raise BookError("qty must be positive")
        lv = self.asks if side == "BUY" else self.bids; rem, cost = qty, D(0)
        for p, q in lv:
            take = min(rem, q); cost += take * p; rem -= take
            if rem <= 0: break
        if rem > 0: raise BookError(f"insufficient depth: {rem} unfilled")
        vwap = cost / qty; ref = self.best_ask if side == "BUY" else self.best_bid
        return {"vwap": vwap, "notional": cost, "impact_bps_vs_best": abs(vwap - ref) / ref * 10000,
                "impact_bps_vs_mid": abs(vwap - self.mid) / self.mid * 10000}

@dataclass
class StalenessGuard:
    """Blocks signal evaluation when data is stale or the clock looks wrong.
    - per-symbol gap: now_ts - last_ts > max_gap_s  -> STALE
    - non-monotonic timestamps                      -> CLOCK_BACKWARDS
    - |exchange_ts - local_ts| > max_drift_s       -> CLOCK_DRIFT (only when a local clock reading is supplied)
    Fails closed: the first tick of a symbol has no reference and is allowed only if allow_first is True."""
    max_gap_s: int = 120; max_drift_s: int = 5; allow_first: bool = True
    _last: dict = field(default_factory=dict); blocked: dict = field(default_factory=dict)
    def check(self, symbol: str, ts: int, local_ts: float | None = None) -> tuple[bool, str]:
        prev = self._last.get(symbol); verdict = (True, "OK")
        if local_ts is not None and abs(D(str(local_ts)) - D(ts)) > self.max_drift_s: verdict = (False, "CLOCK_DRIFT")
        elif prev is None: verdict = (self.allow_first, "OK" if self.allow_first else "NO_REFERENCE")
        elif ts <= prev: verdict = (False, "CLOCK_BACKWARDS")
        elif ts - prev > self.max_gap_s: verdict = (False, "STALE")
        if ts > (prev or 0): self._last[symbol] = ts
        if not verdict[0]: self.blocked[verdict[1]] = self.blocked.get(verdict[1], 0) + 1
        return verdict
