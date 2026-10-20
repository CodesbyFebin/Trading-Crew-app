"""JEV: advisory chat assistant for the dashboard. Original, minimal design.
- Reads app state ONLY through a fixed whitelist of read-only tools that return JSON copies.
- Can append advisory notes to shared memory (kind='advisory', advisory=True). Nothing else is writable.
- Holds no reference to the engine, risk engine, mode controller, kill switch, connectors, approvals or keys.
- Action requests (orders, modes, limits, approvals, keys) are refused deterministically before any LLM call.
- With no LLM key: status NOT CONFIGURED; the real read-only context is still shown, no text is fabricated."""
from __future__ import annotations
import json, re
from dataclasses import dataclass
from typing import Callable
from .llm_router import LLMRouter, NotConfigured, AllProvidersFailed
from .memory import SharedMemory, Fact

READ_TOOLS = ("summary", "risk", "audit", "reports", "memory", "skills", "desks", "india", "backtests")
KEYWORDS = {"risk": ("risk","limit","veto","kill","drawdown","drill"), "audit": ("audit","who","log"),
            "reports": ("report","paper","day"), "memory": ("memory","note","fact"), "skills": ("skill","tool","indicator"),
            "desks": ("desk","d1","d2","d3","d4"), "india": ("india","nse","sebi","d5","fyers"), "backtests": ("backtest","variant","param")}
FORBIDDEN = re.compile(r"\b(buy|sell|place|order|execute|trade now|promote|mode|live|limit[s]? (to|=)|change (the )?limit|"
                       r"approve|approval|reset kill|disable kill|api key|secret|token|private key|seed phrase|withdraw)\b", re.I)
SYSTEM = ("You are JEV, an advisory assistant inside a paper-only trading research dashboard. You may only explain the "
          "JSON context you are given. You cannot place orders, change modes or limits, approve anything, or access keys. "
          "Do not give trade recommendations or promise profits. If the context lacks the answer, say so. Be concise.")

@dataclass(frozen=True)
class JevReply:
    status: str; answer: str | None; tools_used: tuple; context: dict; provider: str | None = None; model: str | None = None
    refused: str | None = None; advisory: bool = True

class Jev:
    def __init__(self, tools: dict[str, Callable[[], object]], memory: SharedMemory, router: LLMRouter):
        bad = set(tools) - set(READ_TOOLS)
        if bad: raise ValueError(f"JEV only accepts read-only tools; rejected: {sorted(bad)}")
        self._tools = {k: (lambda f=f: json.loads(json.dumps(f(), default=str))) for k, f in tools.items()}  # copies only
        self._mem, self._router = memory, router
    def status(self): return self._router.status()
    def _pick(self, q):
        ql = q.lower(); return ["summary"] + [t for t, ks in KEYWORDS.items() if t in self._tools and any(k in ql for k in ks)]
    def ask(self, question: str, save_note: bool = False) -> JevReply:
        q = question.strip()[:2000]
        if FORBIDDEN.search(q) and re.search(r"\b(do|please|can you|set|place|change|approve|send|give|show|reveal|switch|go|make)\b", q, re.I):
            return JevReply("REFUSED", None, (), {}, refused="JEV is advisory only: it cannot place orders, change modes or limits, "
                            "approve, or access keys. Use the Risk Console / Approvals pages with the proper role.")
        used = tuple(dict.fromkeys(self._pick(q)))
        ctx = {t: self._tools[t]() for t in used if t in self._tools}
        if "memory" in used: ctx["memory"] = self._mem.search(q.split()[-1] if q else "", 20) or self._mem.read(limit=20)
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"CONTEXT (JSON, read-only):\n{json.dumps(ctx, default=str)[:24000]}\n\nQUESTION: {q}"}]
        try: note = self._router.complete("JEV", msgs)
        except NotConfigured as e: return JevReply("NOT CONFIGURED", None, used, ctx, refused=str(e))
        except AllProvidersFailed as e: return JevReply("ALL PROVIDERS FAILED", None, used, ctx, refused=str(e))
        if save_note:
            self._mem.write(Fact("JEV", "jev-note", f"Q: {q}\nA: {note.text}", "advisory", f"llm:{note.provider}/{note.model}", advisory=True))
        return JevReply("OK", note.text, used, ctx, note.provider, note.model)
