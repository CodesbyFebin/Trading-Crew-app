"""Deterministic usage limits for advisory LLM calls (JEV). Pure bookkeeping: no network, no keys.
Checks run BEFORE a provider call; a refused call never reaches the provider and writes nothing to memory.
Day window is the UTC calendar day. Calls whose provider returned no usage are charged at max_tokens (conservative)."""
from __future__ import annotations
import json, threading, time
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

CFG = Path(__file__).resolve().parent.parent / "config" / "llm_budget.json"
class BudgetExceeded(Exception): pass

class LLMBudget:
    def __init__(self, cfg: dict | None = None, clock=time.time):
        self.cfg = cfg if cfg is not None else json.loads(CFG.read_text()); self.clock = clock
        self._lock = threading.Lock(); self._recent: dict[str, deque] = {}; self._day = None
        self._calls = 0; self._tokens = 0; self._cost = Decimal(0); self._cost_unknown = False; self._by_role: dict[str, int] = {}
    def _roll(self, now):
        d = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        if d != self._day:
            self._day, self._calls, self._tokens, self._cost, self._cost_unknown, self._by_role = d, 0, 0, Decimal(0), False, {}
    def reserve(self, role: str, max_tokens: int) -> None:
        """Atomically check every limit and count the call. Raises BudgetExceeded (fail safe) at or above any limit."""
        c = self.cfg; now = self.clock()
        with self._lock:
            self._roll(now)
            pm = c["per_role_per_minute"].get(role); pd = c["per_role_per_day"].get(role)
            if pm is None or pd is None: raise BudgetExceeded(f"no LLM allowance for role {role!r}")
            q = self._recent.setdefault(role, deque())
            while q and now - q[0] >= 60: q.popleft()
            if len(q) >= pm: raise BudgetExceeded(f"rate limit: {pm}/min for {role}")
            if self._by_role.get(role, 0) >= pd: raise BudgetExceeded(f"daily call limit for {role}")
            if self._calls >= c["max_calls_per_day"]: raise BudgetExceeded("daily call budget exhausted")
            if self._tokens + max_tokens > c["max_tokens_per_day"]: raise BudgetExceeded("daily token budget exhausted")
            mc = c.get("max_cost_usd_per_day")
            if mc is not None and (self._cost_unknown or self._cost >= Decimal(str(mc))):
                raise BudgetExceeded("daily cost budget exhausted or cost UNKNOWN (cannot be bounded)")
            q.append(now); self._calls += 1; self._by_role[role] = self._by_role.get(role, 0) + 1
            self._tokens += max_tokens          # provisional charge, corrected by settle()
    def settle(self, max_tokens: int, used_tokens: int | None, cost_usd: str | None) -> None:
        with self._lock:
            if used_tokens is not None: self._tokens += used_tokens - max_tokens   # replace provisional charge with reported usage
            if cost_usd in (None, "UNKNOWN"): self._cost_unknown = True
            else: self._cost += Decimal(cost_usd)
    def release(self, max_tokens: int) -> None:
        """Provider not reached / failed: keep the call counted (rate limit holds) but refund the token reservation."""
        with self._lock: self._tokens = max(0, self._tokens - max_tokens)
    def status(self) -> dict:
        with self._lock:
            self._roll(self.clock())
            return {"day_utc": self._day, "calls": self._calls, "tokens_charged": self._tokens,
                    "cost_usd": "UNKNOWN" if self._cost_unknown else str(self._cost), "limits": {k: v for k, v in self.cfg.items() if not k.startswith("_")}}
