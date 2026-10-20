"""Deterministic risk engine. Decimal only. Fails closed. At-limit == breach."""
from __future__ import annotations
import hashlib, json, threading, queue
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any
from .models import RiskEvent

class LimitsTamper(Exception): pass

class Limits:
    """Immutable limits loaded from file; any mutation raises and is logged."""
    __slots__ = ("_d","sha256","_log","_digest")
    def __init__(self, path: str | Path, log=None):
        raw = Path(path).read_bytes()
        object.__setattr__(self,"sha256",hashlib.sha256(raw).hexdigest())
        d = json.loads(raw)
        for k,v in d.items():
            if isinstance(v,str): d[k]=Decimal(v)
        object.__setattr__(self,"_d",MappingProxyType(d))
        object.__setattr__(self,"_log",log if log is not None else [])
        object.__setattr__(self,"_digest",self._content_digest())
    def _content_digest(self) -> str:
        d = object.__getattribute__(self,"_d")
        return hashlib.sha256(json.dumps({k: str(v) for k, v in d.items()}, sort_keys=True).encode()).hexdigest()
    def intact(self) -> bool:
        """False if the in-memory values were swapped behind the read-only guard (e.g. via object.__setattr__)."""
        try: ok = isinstance(object.__getattribute__(self,"_d"), MappingProxyType) and self._content_digest() == object.__getattribute__(self,"_digest")
        except Exception: ok = False
        if not ok: self._log.append(RiskEvent("LIMITS_TAMPER", None, "in-memory limits digest mismatch", "CRITICAL"))
        return ok
    def __getattr__(self, k):
        try: return object.__getattribute__(self,"_d")[k]
        except KeyError: raise AttributeError(k)
    def __setattr__(self, k, v):
        self._log.append(RiskEvent("LIMITS_TAMPER", None, f"attempt to set {k}={v!r}", "CRITICAL"))
        raise LimitsTamper(f"limits are read-only at runtime ({k})")
    __delattr__ = lambda self,k: self.__setattr__(k, "<delete>")
    @property
    def tamper_log(self): return self._log

class LimitsAuditor:
    def __init__(self, limits: Limits, path): self.limits, self.path = limits, Path(path)
    def check(self) -> bool:
        ok = hashlib.sha256(self.path.read_bytes()).hexdigest() == self.limits.sha256
        if not ok: self.limits.tamper_log.append(RiskEvent("LIMITS_FILE_CHANGED", None, "limits file hash mismatch", "CRITICAL"))
        return ok

@dataclass(frozen=True)
class OrderIntent:
    ticket_id: str; venue: str; notional: Decimal; expected_slippage_bps: Decimal; liquidity_usd: Decimal
    is_withdrawal: bool = False

@dataclass(frozen=True)
class Portfolio:
    equity: Decimal; gross_exposure: Decimal; venue_exposure: dict
    open_positions: int; daily_pnl: Decimal; weekly_pnl: Decimal
    peak_equity: Decimal; seconds_since_last_loss: int | None
    # Equity at the start of the current UTC day (last mark before 00:00 UTC). daily_pnl is
    # realized + unrealized (mark-to-market) change since then. None = use current equity (legacy callers).
    day_start_equity: Decimal | None = None

@dataclass(frozen=True)
class Decision:
    approved: bool; reasons: tuple[str,...]

DAILY_LOSS_REASON = "daily loss limit breached"   # engine engages the global kill on this veto

def daily_loss_base(equity: Decimal, day_start_equity: Decimal | None) -> Decimal:
    """Denominator for the daily-loss limit: the smaller of start-of-day and current equity (conservative)."""
    return equity if day_start_equity is None else min(equity, day_start_equity)

def daily_loss_breached(limits, daily_pnl: Decimal, equity: Decimal, day_start_equity: Decimal | None = None) -> bool:
    """Pure, deterministic. At-limit == breach (same >= semantics as every other limit)."""
    return -daily_pnl >= limits.daily_loss_pct * daily_loss_base(equity, day_start_equity)

def _finite(x) -> bool: return isinstance(x, Decimal) and x.is_finite()
def _int(x) -> bool: return isinstance(x, int) and not isinstance(x, bool)

def validate_inputs(o, p) -> list[str]:
    """Reasons the inputs are malformed (empty list = well-formed). Any reason => reject (fail closed)."""
    r = []
    if not isinstance(o.ticket_id, str) or not o.ticket_id: r.append("fail-closed: ticket_id invalid")
    if not isinstance(o.venue, str) or not o.venue: r.append("fail-closed: venue invalid")
    if not isinstance(o.is_withdrawal, bool): r.append("fail-closed: is_withdrawal not bool")
    for name in ("notional","expected_slippage_bps","liquidity_usd"):
        v = getattr(o, name)
        if not isinstance(v, Decimal): r.append(f"fail-closed: {name} not Decimal")
        elif not v.is_finite(): r.append(f"fail-closed: {name} not finite")
        elif v < 0: r.append(f"fail-closed: {name} negative")
    for name in ("equity","gross_exposure","daily_pnl","weekly_pnl","peak_equity"):
        v = getattr(p, name)
        if not isinstance(v, Decimal): r.append(f"fail-closed: {name} not Decimal")
        elif not v.is_finite(): r.append(f"fail-closed: {name} not finite")
    if _finite(p.gross_exposure) and p.gross_exposure < 0: r.append("fail-closed: gross_exposure negative")
    if _finite(p.peak_equity) and p.peak_equity < 0: r.append("fail-closed: peak_equity negative")
    if p.day_start_equity is not None and not (_finite(p.day_start_equity) and p.day_start_equity > 0):
        r.append("fail-closed: day_start_equity invalid")
    if not _int(p.open_positions) or p.open_positions < 0: r.append("fail-closed: open_positions invalid")
    if p.seconds_since_last_loss is not None and (not _int(p.seconds_since_last_loss) or p.seconds_since_last_loss < 0):
        r.append("fail-closed: seconds_since_last_loss invalid")
    if not isinstance(p.venue_exposure, dict): r.append("fail-closed: venue_exposure not a dict")
    else:
        for k, v in p.venue_exposure.items():
            if not isinstance(k, str) or not _finite(v) or v < 0: r.append(f"fail-closed: venue_exposure[{k!r}] invalid"); break
        else:
            if _finite(p.gross_exposure) and sum(p.venue_exposure.values(), Decimal(0)) > p.gross_exposure:
                r.append("fail-closed: venue exposure exceeds gross exposure")
    return r

class RiskEngine:
    def __init__(self, limits: Limits, kill_switch=None, auditor: LimitsAuditor | None = None):
        self.limits, self.kill, self.auditor = limits, kill_switch, auditor
        self.events: list[RiskEvent] = []
        self.halted_reason: str | None = None
        # One daemon worker bounds outstanding risk checks. If a check times out and
        # cannot be interrupted, later checks fail closed until it finishes; repeated
        # timeouts cannot create an unbounded number of threads.
        self._work: queue.Queue = queue.Queue(maxsize=1)
        self._pending_lock = threading.Lock()
        self._pending: Future | None = None
        self._worker = threading.Thread(target=self._worker_loop, name="risk-check", daemon=True)
        self._worker.start()
    def _reject(self, tid, reasons):
        for r in reasons: self.events.append(RiskEvent("VETO", tid, r))
        return Decision(False, tuple(reasons))
    def check(self, o: Any, p: Any, timeout_s: float = 1.0) -> Decision:
        tid = getattr(o, "ticket_id", None)
        if timeout_s <= 0: return self._reject(tid, ["fail-closed: invalid risk check timeout"])
        with self._pending_lock:
            if self._pending is not None and not self._pending.done():
                return self._reject(tid, ["fail-closed: previous risk check is still running"])
            fut: Future = Future()
            self._pending = fut
            self._work.put_nowait((o, p, fut))
        try:
            r = fut.result(timeout=timeout_s)
        except FutureTimeout:
            return self._reject(tid, ["fail-closed: risk check timeout"])
        except Exception as e:
            return self._reject(tid, [f"fail-closed: {type(e).__name__}: {e}"])
        if not isinstance(r, Decision) or not isinstance(r.approved, bool) or not isinstance(r.reasons, tuple):
            return self._reject(tid, ["fail-closed: bad decision type"])
        if r.approved and r.reasons: return self._reject(tid, ["fail-closed: approval carried reasons"])
        # Re-check state that can change while the worker ran: kill and limits integrity.
        if r.approved and self.kill is not None and self.kill.engaged: return self._reject(tid, ["panic kill engaged"])
        if r.approved and not self.limits.intact(): return self._reject(tid, ["limits tampered in memory"])
        return r
    def _worker_loop(self):
        while True:
            o, p, fut = self._work.get()
            if not fut.set_running_or_notify_cancel(): continue
            try: fut.set_result(self._check(o, p))
            except Exception as e: fut.set_exception(e)
    def _check(self, o, p) -> Decision:
        if not isinstance(o, OrderIntent) or not isinstance(p, Portfolio):
            return self._reject(getattr(o,"ticket_id",None), ["fail-closed: wrong input type"])
        bad = validate_inputs(o, p)
        if bad: return self._reject(o.ticket_id, bad)
        L, r = self.limits, []
        if not L.intact(): r.append("limits tampered in memory")
        if self.kill is not None and self.kill.engaged: r.append("panic kill engaged")
        if self.auditor is not None and not self.auditor.check(): r.append("limits file tampered")
        if self.halted_reason: r.append(f"halted: {self.halted_reason}")
        if o.is_withdrawal and not L.withdrawal_enabled: r.append("withdrawals disabled")
        if p.equity <= 0: r.append("non-positive equity")
        else:
            if o.notional <= 0: r.append("non-positive notional")
            if o.notional >= L.max_position_pct * p.equity: r.append("max position % breached")
            if p.gross_exposure + o.notional >= L.max_gross_exposure_pct * p.equity: r.append("gross exposure breached")
            ve = p.venue_exposure.get(o.venue, Decimal(0))
            if ve + o.notional >= L.per_venue_cap_pct * p.equity: r.append("per-venue cap breached")
            if daily_loss_breached(L, p.daily_pnl, p.equity, p.day_start_equity): r.append(DAILY_LOSS_REASON)
            if -p.weekly_pnl >= L.weekly_loss_pct * p.equity: r.append("weekly loss limit breached")
            if p.peak_equity > 0 and (p.peak_equity - p.equity) >= L.drawdown_halt_pct * p.peak_equity:
                self.halted_reason = "drawdown halt"; r.append("drawdown halt")
        if o.expected_slippage_bps >= L.max_slippage_bps: r.append("slippage limit breached")
        if o.liquidity_usd <= L.min_liquidity_usd: r.append("min liquidity breached")
        if p.open_positions >= L.max_open_positions: r.append("max open positions breached")
        if p.seconds_since_last_loss is not None and p.seconds_since_last_loss <= L.post_loss_cooldown_s: r.append("post-loss cooldown")
        return self._reject(o.ticket_id, r) if r else Decision(True, ())


def utilisation(L, o: OrderIntent, p: Portfolio) -> dict:
    """Utilisation of each real limit for one checked intent, as value/limit (Decimal). >= 1 means breach
    (the engine treats at-limit as a breach). Pure function, used for display only; RiskEngine._check decides."""
    eq, z = p.equity, Decimal(0)
    def r(a, b): return (a / b) if b > 0 else None
    ve = p.venue_exposure.get(o.venue, z)
    u = {"max_position_pct": r(o.notional, L.max_position_pct * eq),
         "max_gross_exposure_pct": r(p.gross_exposure + o.notional, L.max_gross_exposure_pct * eq),
         "per_venue_cap_pct": r(ve + o.notional, L.per_venue_cap_pct * eq),
         "daily_loss_pct": r(max(z, -p.daily_pnl), L.daily_loss_pct * daily_loss_base(eq, p.day_start_equity)),
         "weekly_loss_pct": r(max(z, -p.weekly_pnl), L.weekly_loss_pct * eq),
         "drawdown_halt_pct": r(max(z, p.peak_equity - eq), L.drawdown_halt_pct * p.peak_equity),
         "max_slippage_bps": r(o.expected_slippage_bps, Decimal(L.max_slippage_bps)),
         "min_liquidity_usd": r(Decimal(L.min_liquidity_usd), o.liquidity_usd),
         "max_open_positions": r(Decimal(p.open_positions), Decimal(L.max_open_positions)),
         "post_loss_cooldown_s": z if p.seconds_since_last_loss is None else r(Decimal(L.post_loss_cooldown_s), Decimal(max(p.seconds_since_last_loss, 1))),
         "withdrawal_enabled": z if not o.is_withdrawal else Decimal(1)}
    return u
