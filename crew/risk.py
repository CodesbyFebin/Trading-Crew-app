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
    __slots__ = ("_d","sha256","_log")
    def __init__(self, path: str | Path, log=None):
        raw = Path(path).read_bytes()
        object.__setattr__(self,"sha256",hashlib.sha256(raw).hexdigest())
        d = json.loads(raw)
        for k,v in d.items():
            if isinstance(v,str): d[k]=Decimal(v)
        object.__setattr__(self,"_d",MappingProxyType(d))
        object.__setattr__(self,"_log",log if log is not None else [])
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

@dataclass(frozen=True)
class Decision:
    approved: bool; reasons: tuple[str,...]

DAILY_LOSS_REASON = "daily loss limit breached"   # engine engages the global kill on this veto

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
        if not isinstance(r, Decision): return self._reject(tid, ["fail-closed: bad decision type"])
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
        for name in ("notional","expected_slippage_bps","liquidity_usd"):
            if not isinstance(getattr(o,name), Decimal): return self._reject(o.ticket_id,[f"fail-closed: {name} not Decimal"])
        for name in ("equity","gross_exposure","daily_pnl","weekly_pnl","peak_equity"):
            if not isinstance(getattr(p,name), Decimal): return self._reject(o.ticket_id,[f"fail-closed: {name} not Decimal"])
        L, r = self.limits, []
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
            if -p.daily_pnl >= L.daily_loss_pct * p.equity: r.append(DAILY_LOSS_REASON)
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
         "daily_loss_pct": r(max(z, -p.daily_pnl), L.daily_loss_pct * eq),
         "weekly_loss_pct": r(max(z, -p.weekly_pnl), L.weekly_loss_pct * eq),
         "drawdown_halt_pct": r(max(z, p.peak_equity - eq), L.drawdown_halt_pct * p.peak_equity),
         "max_slippage_bps": r(o.expected_slippage_bps, Decimal(L.max_slippage_bps)),
         "min_liquidity_usd": r(Decimal(L.min_liquidity_usd), o.liquidity_usd),
         "max_open_positions": r(Decimal(p.open_positions), Decimal(L.max_open_positions)),
         "post_loss_cooldown_s": z if p.seconds_since_last_loss is None else r(Decimal(L.post_loss_cooldown_s), Decimal(max(p.seconds_since_last_loss, 1))),
         "withdrawal_enabled": z if not o.is_withdrawal else Decimal(1)}
    return u
