"""TA research desk (OPTIONAL, OFF by default): LLM-written research TEXT only.
Prompt patterns (market analyst, bull/bear researchers) adapted from TradingAgents (Apache-2.0); see
third_party/tradingagents/NOTICE.md. Nothing else from that project is used.

Boundaries (enforced by tests/test_research_ta.py):
- Enabled only with CREW_RESEARCH_TA=1. Network data only with CREW_RESEARCH_TA_NETWORK=1 AND an owner caller;
  that data is labelled UNVERIFIED_THIRD_PARTY. Default input = bundled synthetic replay fixture (SYNTHETIC_REPLAY).
- Every LLM call goes through LLMRouter after an LLMBudget reservation. No portfolio context, no memory read-back,
  no reflection, no ratings field. Output = advisory facts + a markdown report marked "LLM opinion, not a signal".
- Imports nothing from engine/risk/modes/killswitch/connectors/store/desk code; those modules never import this one."""
from __future__ import annotations
import json, os, re, time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from .llm_router import LLMRouter, NotConfigured, AllProvidersFailed
from .llm_budget import LLMBudget, BudgetExceeded
from .memory import SharedMemory, Fact

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "binance_replay_sample.jsonl"
BANNER = "LLM opinion, not a signal. Research text only; it cannot place orders or change risk, modes, limits or the kill switch."
MAX_TOKENS = 700
SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,15}$")

class Disabled(Exception): pass

def enabled(env=os.environ) -> bool: return env.get("CREW_RESEARCH_TA") == "1"
def network_allowed(env=os.environ) -> bool: return env.get("CREW_RESEARCH_TA_NETWORK") == "1"

ANALYST = ("You are a market analyst in a PAPER-ONLY research dashboard. Using ONLY the JSON facts below, write a concise "
           "report on trend, momentum and volatility. Treat the facts as the source of truth; never invent prices, dates, "
           "percentages or indicator values that are not in them, and say 'unavailable' when something is missing. "
           "State the data status label exactly as given. Do not give a buy/sell rating or position size. End with a "
           "short Markdown table of the key points.")
BULL = ("You are a Bull Analyst. Build the strongest evidence-based case FOR the instrument using only the analyst report "
        "and facts. Address the bear's concerns directly. Do not invent data, do not promise profit, give no rating or size.")
BEAR = ("You are a Bear Analyst. Present the strongest evidence-based case AGAINST the instrument: risks, weaknesses, "
        "negative indicators. Rebut the bull argument directly. Do not invent data, give no rating or size.")

def _ema(xs, n):
    a, e = Decimal(2) / (n + 1), None
    for x in xs: e = x if e is None else e + a * (x - e)
    return e

def fixture_facts(symbol: str) -> dict:
    """Deterministic facts computed from the bundled synthetic replay fixture (real arithmetic on synthetic prices).
    Reads the fixture file directly so this module imports no strategy/engine code."""
    rows = [json.loads(l) for l in FIXTURE.read_text().splitlines()]
    rows = sorted((r for r in rows if r.get("type") == "market" and r.get("symbol") == symbol), key=lambda r: int(r["ts"]))
    if not rows: raise ValueError(f"no fixture data for {symbol}")
    mids = [(Decimal(str(r["bid"])) + Decimal(str(r["ask"]))) / 2 for r in rows]
    rets = [mids[i] / mids[i - 1] - 1 for i in range(max(1, len(mids) - 60), len(mids))]
    mu = sum(rets, Decimal(0)) / len(rets) if rets else Decimal(0)
    vol = (sum(((r - mu) ** 2 for r in rets), Decimal(0)) / len(rets)).sqrt() if rets else Decimal(0)
    iso = lambda t: datetime.fromtimestamp(int(t), timezone.utc).isoformat()
    q = lambda x, e: str(x.quantize(Decimal(e)))
    return {"symbol": symbol, "data_status": "SYNTHETIC_REPLAY", "verified_historical": False, "source": "fixtures/binance_replay_sample.jsonl",
            "time_range_utc": [iso(rows[0]["ts"]), iso(rows[-1]["ts"])], "ticks": len(rows), "first_mid": str(mids[0]), "last_mid": str(mids[-1]),
            "return_pct": q((mids[-1] / mids[0] - 1) * 100, "0.0001"), "ema20_last": q(_ema(mids, 20), "0.01"),
            "ema60_last": q(_ema(mids, 60), "0.01"), "vol_per_tick_last60": q(vol, "0.0000001"),
            "news": "unavailable", "sentiment": "unavailable", "fundamentals": "unavailable"}

def network_facts(symbol: str) -> dict:   # pragma: no cover - needs optional dependency + network + owner flag
    try: import yfinance as yf
    except ImportError: raise Disabled("network mode needs requirements-research.txt (yfinance) installed")
    h = yf.Ticker(symbol).history(period="1mo")
    if h.empty: raise ValueError(f"no third-party data for {symbol}")
    c = h["Close"]
    return {"symbol": symbol, "data_status": "UNVERIFIED_THIRD_PARTY", "verified_historical": False, "source": "yfinance (Yahoo Finance, unofficial)",
            "time_range_utc": [str(h.index[0]), str(h.index[-1])], "rows": int(len(h)), "first_close": str(c.iloc[0]), "last_close": str(c.iloc[-1]),
            "news": "unavailable", "sentiment": "unavailable", "fundamentals": "unavailable"}

@dataclass
class TAResult:
    status: str; symbol: str; facts: dict = field(default_factory=dict); sections: dict = field(default_factory=dict)
    report_path: str | None = None; detail: str | None = None; advisory: bool = True; banner: str = BANNER

class ResearchDesk:
    def __init__(self, router: LLMRouter, budget: LLMBudget, memory: SharedMemory, out_dir: Path = ROOT / "reports",
                 env=os.environ, fetch_network=network_facts):
        self._router, self._budget, self._mem, self._out, self._env, self._net = router, budget, memory, Path(out_dir), env, fetch_network
    def _call(self, role: str, system: str, user: str) -> str:
        self._budget.reserve(role, MAX_TOKENS)
        try: n = self._router.complete("RTA", [{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=MAX_TOKENS)
        except Exception: self._budget.release(MAX_TOKENS); raise
        pt, ct = n.prompt_tokens, n.completion_tokens
        self._budget.settle(MAX_TOKENS, None if pt is None or ct is None else pt + ct, n.cost_usd)
        return n.text
    def run(self, symbol: str, role: str, source: str = "fixture") -> TAResult:
        if not enabled(self._env): raise Disabled("TA research desk is off (set CREW_RESEARCH_TA=1)")
        if role not in ("owner", "operator"): raise PermissionError("TA research needs operator or owner")
        if not isinstance(symbol, str) or not SYMBOL_RE.match(symbol): raise ValueError("bad symbol")
        if source == "network":
            if role != "owner" or not network_allowed(self._env): raise Disabled("network data needs CREW_RESEARCH_TA_NETWORK=1 and the owner role")
            facts = self._net(symbol)
        elif source == "fixture": facts = fixture_facts(symbol)
        else: raise ValueError("source must be fixture or network")
        if not self._router.configured(): return TAResult("NOT CONFIGURED", symbol, facts, detail="no LLM provider key in env")
        fj = json.dumps(facts)
        try:
            a = self._call(role, ANALYST, f"FACTS (JSON):\n{fj}")
            bull = self._call(role, BULL, f"FACTS:\n{fj}\n\nANALYST REPORT:\n{a}\n\nLast bear argument: (none yet)")
            bear = self._call(role, BEAR, f"FACTS:\n{fj}\n\nANALYST REPORT:\n{a}\n\nLast bull argument:\n{bull}")
        except BudgetExceeded as e: return TAResult("LIMITED", symbol, facts, detail=str(e))
        except (NotConfigured, AllProvidersFailed) as e: return TAResult("ALL PROVIDERS FAILED", symbol, facts, detail=type(e).__name__)
        sections = {"analyst": a, "bull": bull, "bear": bear}
        prov = f"research-ta:{facts['data_status']}:{facts['source']}"
        for k, txt in sections.items():
            self._mem.write(Fact("RTA", f"research-ta:{symbol}", f"[{BANNER}] [{k}] {txt}", "advisory", prov, advisory=True))
        return TAResult("OK", symbol, facts, sections, str(self._write(symbol, facts, sections)))
    def _write(self, symbol, facts, sections) -> Path:
        self._out.mkdir(parents=True, exist_ok=True)
        q = lambda t: "\n".join("> " + ln for ln in t.splitlines())   # LLM text is quoted, never parsed
        md = [f"# TA research desk: {symbol}", "", f"**{BANNER}**", "",
              f"- Data status: **{facts['data_status']}** (verified historical: {facts['verified_historical']})",
              f"- Source: {facts['source']}; time range (UTC): {facts['time_range_utc'][0]} → {facts['time_range_utc'][1]}",
              "- Prompt patterns adapted from TradingAgents (Apache-2.0), see third_party/tradingagents/NOTICE.md", "",
              "## Facts given to the model (computed, not LLM)", "```json", json.dumps(facts, indent=1), "```"]
        for k in ("analyst", "bull", "bear"): md += ["", f"## {k.title()} (LLM text, quoted verbatim)", q(sections[k])]
        p = self._out / f"research-ta-{symbol}-{time.strftime('%Y%m%d-%H%M%S')}.md"; p.write_text("\n".join(md) + "\n"); return p
