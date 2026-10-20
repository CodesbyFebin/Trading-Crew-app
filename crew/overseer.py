"""Main Grok overseer as deterministic code. Never places orders, never touches keys."""
from __future__ import annotations
import asyncio, time
from dataclasses import dataclass, field
from .agents import Registry, AgentDisabled
from .models import Ticket, TraceRow, TicketState as S
from .store import SQLiteStore

@dataclass
class Budget:
    llm_tokens_limit: int = 0          # owner rule: no LLM calls
    llm_tokens_used: int = 0
    compute_ms_limit: float = 600_000.0
    compute_ms_used: float = 0.0
    def ok(self) -> bool: return self.llm_tokens_used <= self.llm_tokens_limit and self.compute_ms_used < self.compute_ms_limit

@dataclass(frozen=True)
class LaneResult:
    agent_id: str; ok: bool; verdict: str | None; detail: str

class MainGrok:
    ROUTES = {"crypto_signal": "D4", "prediction": "D1", "filing": "D2", "token": "D3"}
    def __init__(self, reg: Registry, store: SQLiteStore, quorum: int = 2):
        self.reg, self.store, self.quorum = reg, store, quorum
        self.budget = Budget(); self.escalations: list[dict] = []; self.tickets: dict[str, Ticket] = {}
    def route(self, kind: str) -> str:
        if kind not in self.ROUTES: raise KeyError(f"no route for {kind}")
        return self.ROUTES[kind]
    def open_ticket(self, kind, instrument, venue) -> Ticket:
        t = Ticket(self.route(kind), instrument, venue); self.tickets[t.ticket_id] = t
        self.trace(t, "MAIN", "MAIN", "open", "CLAIM", f"opened {kind} ticket for {instrument}"); return t
    def trace(self, t, agent, crew, stage, typ, content, ev=()):
        self.store.append_trace(TraceRow(t.ticket_id, agent, crew, stage, typ, content, tuple(ev)))
    async def fan_out(self, t: Ticket, lanes: dict, deadline_s: float = 2.0) -> list[LaneResult]:
        async def one(aid, fn):
            a = self.reg[aid]
            try:
                v = await asyncio.wait_for(a.run(fn), deadline_s); return LaneResult(aid, True, v, "")
            except AgentDisabled as e: return LaneResult(aid, False, None, str(e))
            except asyncio.TimeoutError: return LaneResult(aid, False, None, "deadline exceeded")
            except Exception as e: return LaneResult(aid, False, None, f"{type(e).__name__}: {e}")
        t0 = time.perf_counter()
        res = await asyncio.gather(*(one(a, f) for a, f in lanes.items()))   # fan-in
        self.budget.compute_ms_used += (time.perf_counter()-t0)*1000
        for r in res:
            self.trace(t, r.agent_id, self.reg[r.agent_id].crew, "lane", "RESULT" if r.ok else "ERROR",
                       f"verdict={r.verdict}" if r.ok else r.detail)
        return res
    def arbitrate(self, t: Ticket, res: list[LaneResult], want: str) -> bool:
        good = [r for r in res if r.ok and r.verdict is not None]
        agree = [r for r in good if r.verdict == want]
        if not self.budget.ok():
            return self._esc(t, "budget exhausted")
        if len(good) < self.quorum:
            return self._esc(t, f"quorum not met: {len(good)}/{self.quorum} lanes returned")
        if len(agree) < self.quorum:
            self.trace(t, "MAIN", "MAIN", "arbiter", "RESULT",
                       f"rationale: lanes disagree ({', '.join(f'{r.agent_id}={r.verdict}' for r in good)}); no action")
            return False
        self.trace(t, "MAIN", "MAIN", "arbiter", "RESULT",
                   f"rationale: {len(agree)} independent lanes agree on {want} ({', '.join(r.agent_id for r in agree)})")
        return True
    def _esc(self, t, why):
        self.escalations.append({"ticket_id": t.ticket_id, "reason": why})
        self.trace(t, "MAIN", "MAIN", "escalate", "ESCALATE", why); return False
