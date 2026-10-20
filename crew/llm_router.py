"""ADVISORY-ONLY model routing gateway (OpenAI-compatible /chat/completions).
Routes to free-tier providers configured in config/llm_routing.json, keys from env only, fallback order + timeouts.
No key -> status NOT CONFIGURED and NotConfigured raised; responses are never fabricated.
Output is an AdvisoryNote (text only). This module imports nothing from order/risk/mode code, and those modules
are tested never to import it (tests/test_llm_isolation.py)."""
from __future__ import annotations
import json, os, time
from dataclasses import dataclass
from pathlib import Path
import httpx

CFG = Path(__file__).resolve().parent.parent / "config" / "llm_routing.json"
class NotConfigured(Exception): pass
class AllProvidersFailed(Exception): pass

@dataclass(frozen=True)
class AdvisoryNote:
    text: str; provider: str; model: str; latency_ms: float; advisory: bool = True
    disclaimer: str = "ADVISORY TEXT ONLY - cannot place orders, change modes/limits, or approve anything"

def load_cfg(path=CFG): return json.loads(Path(path).read_text())

class LLMRouter:
    def __init__(self, cfg: dict | None = None, env=None, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg or load_cfg(); self.env = env if env is not None else os.environ; self.transport = transport
        self.log: list[dict] = []
    def _routes(self):
        out = []
        for name in self.cfg["fallback_order"]:
            p = self.cfg["providers"][name]; key = self.env.get(p["key_env"], "")
            models = list(p.get("models", []))
            if p.get("model_env") and self.env.get(p["model_env"]): models = [self.env[p["model_env"]]] + models
            base = self.env.get(p.get("base_url_env", ""), "") or p["base_url"]
            out.append((name, base.rstrip("/"), key, models))
        return out
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
                        r.raise_for_status(); txt = r.json()["choices"][0]["message"]["content"]
                        if not isinstance(txt, str) or not txt.strip(): raise ValueError("empty completion")
                        ms = round((time.perf_counter()-t)*1000, 1)
                        self.log.append({"agent": agent_id, "provider": name, "model": model, "ok": True, "ms": ms})
                        return AdvisoryNote(txt, name, model, ms)
                    except Exception as e:
                        errs.append(f"{name}/{model}: {type(e).__name__}")
                        self.log.append({"agent": agent_id, "provider": name, "model": model, "ok": False, "error": type(e).__name__})
        raise AllProvidersFailed("; ".join(errs))
