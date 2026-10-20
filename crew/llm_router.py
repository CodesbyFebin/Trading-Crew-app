"""ADVISORY-ONLY model routing gateway (OpenAI-compatible /chat/completions).
Routes to free-tier providers configured in config/llm_routing.json, keys from env only, fallback order + timeouts.
No key -> status NOT CONFIGURED and NotConfigured raised; responses are never fabricated.
Output is an AdvisoryNote (text only). This module imports nothing from order/risk/mode code, and those modules
are tested never to import it (tests/test_llm_isolation.py)."""
from __future__ import annotations
import json, os, time
from decimal import Decimal
from dataclasses import dataclass
from pathlib import Path
import httpx

CFG = Path(__file__).resolve().parent.parent / "config" / "llm_routing.json"
PRICING = CFG.parent / "llm_pricing.json"
class NotConfigured(Exception): pass
class AllProvidersFailed(Exception): pass

@dataclass(frozen=True)
class AdvisoryNote:
    text: str; provider: str; model: str; latency_ms: float; advisory: bool = True
    prompt_tokens: int | None = None; completion_tokens: int | None = None
    cost_usd: str = "UNKNOWN"   # Decimal string from verified pricing, or "UNKNOWN"
    disclaimer: str = "ADVISORY TEXT ONLY - cannot place orders, change modes/limits, or approve anything"

def load_cfg(path=CFG): return json.loads(Path(path).read_text())
def load_pricing(path=PRICING): return json.loads(Path(path).read_text())["prices"] if Path(path).exists() else {}

def cost_of(pricing: dict, provider: str, model: str, pt: int | None, ct: int | None) -> str:
    """Cost only from a verified price entry and provider-reported usage; otherwise "UNKNOWN"."""
    p = pricing.get(f"{provider}/{model}")
    if p is None or pt is None or ct is None: return "UNKNOWN"
    return str(Decimal(p["prompt"]) * pt + Decimal(p["completion"]) * ct)

class LLMRouter:
    def __init__(self, cfg: dict | None = None, env=None, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg or load_cfg(); self.env = env if env is not None else os.environ; self.transport = transport
        self.log: list[dict] = []; self.pricing = load_pricing()
    def totals(self) -> dict:
        ok = [c for c in self.log if c["ok"]]
        known = [c for c in ok if c.get("cost_usd") not in (None, "UNKNOWN")]
        pt = sum(c.get("prompt_tokens") or 0 for c in ok); ct = sum(c.get("completion_tokens") or 0 for c in ok)
        cost = str(sum((Decimal(c["cost_usd"]) for c in known), Decimal(0))) if len(known) == len(ok) else "UNKNOWN"
        return {"calls": len(ok), "failed_calls": len(self.log) - len(ok), "prompt_tokens": pt, "completion_tokens": ct,
                "tokens": pt + ct, "cost_usd": cost, "calls_without_usage": sum(1 for c in ok if c.get("prompt_tokens") is None)}
    def _routes(self):
        out = []
        for name in self.cfg["fallback_order"]:
            p = self.cfg["providers"][name]; key = self.env.get(p["key_env"], "")
            models = list(p.get("models", []))
            if p.get("model_env") and self.env.get(p["model_env"]): models = [self.env[p["model_env"]]] + models
            base = self.env.get(p.get("base_url_env", ""), "") or p["base_url"]
            out.append((name, base.rstrip("/"), key, models))
        return out
    def configured(self) -> bool: return any(k and m for _, _, k, m in self._routes())
    def status(self) -> dict:
        provs = {n: ("CONFIGURED" if k and m else "NO MODEL (set model env)" if k else "NOT CONFIGURED") for n, _, k, m in self._routes()}
        return {"status": "CONFIGURED" if "CONFIGURED" in provs.values() else "NOT CONFIGURED", "providers": provs,
                "fallback_order": self.cfg["fallback_order"], "agent_models": self.cfg.get("agent_models", {}),
                "policy": "advisory text only; never reaches order/risk/mode code"}
    def complete(self, agent_id: str, messages: list[dict], max_tokens=600) -> AdvisoryNote:
        routes = [r for r in self._routes() if r[2] and r[3]]
        if not routes: raise NotConfigured("NOT CONFIGURED: no LLM provider key in env (OPENROUTER_API_KEY / KILOCODE_API_KEY / GROQ_API_KEY / CLINE_API_KEY)")
        errs = []
        with httpx.Client(timeout=self.cfg.get("timeout_s", 30), transport=self.transport) as c:
            for name, base, key, models in routes:
                for model in models:
                    t = time.perf_counter()
                    try:
                        r = c.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                                   json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2, "stream": False})
                        r.raise_for_status(); body = r.json(); txt = body["choices"][0]["message"]["content"]
                        u = body.get("usage") or {}
                        pt, ct = u.get("prompt_tokens"), u.get("completion_tokens")
                        pt = pt if isinstance(pt, int) else None; ct = ct if isinstance(ct, int) else None
                        if not isinstance(txt, str) or not txt.strip(): raise ValueError("empty completion")
                        ms = round((time.perf_counter()-t)*1000, 1)
                        cost = cost_of(self.pricing, name, model, pt, ct)
                        self.log.append({"agent": agent_id, "provider": name, "model": model, "ok": True, "ms": ms,
                                         "prompt_tokens": pt, "completion_tokens": ct, "cost_usd": cost})
                        return AdvisoryNote(txt, name, model, ms, prompt_tokens=pt, completion_tokens=ct, cost_usd=cost)
                    except Exception as e:
                        errs.append(f"{name}/{model}: {type(e).__name__}")
                        self.log.append({"agent": agent_id, "provider": name, "model": model, "ok": False, "error": type(e).__name__})
        raise AllProvidersFailed("; ".join(errs))
