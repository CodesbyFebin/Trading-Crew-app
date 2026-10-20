"""Crew registry: 50 sub-agents as independent async workers with real metrics.
Names S01-S23 follow the blueprint; the pasted blueprint was truncated after S24, so names for S24-S50
are inferred from crew roles and are documented as such in the README."""
from __future__ import annotations
import asyncio, time
from dataclasses import dataclass, field
from typing import Any, Callable

ENABLED, DISABLED, NOT_APPROVED, IDLE = "ENABLED", "DISABLED_BY_POLICY", "NOT_APPROVED_BY_OWNER", "DISABLED_IDLE"
POL_EXT = "needs external data feed; no network in this build"
POL_LLM = "LLM role; owner rule: LLMs never make trade/risk decisions and no LLM calls in this build"
POL_LIVE = "live venue/wallet executor; LIVE_ENABLED=false and live gates cannot pass in this build"
POL_NEWS = "news/social only via deterministic event calendar per owner rule; feed not connected"

# id, name, crew, task, state, reason, desk
SPEC = [
 ("S01","TapeWatcher","C1","Trade/book stream (replay fixture)",ENABLED,"","D4"),
 ("S02","OracleSync","C1","Pyth/Chainlink staleness checks",DISABLED,POL_EXT,""),
 ("S03","PredictionBook","C1","Prediction-market catalog (synthetic fixture)",ENABLED,"","D1"),
 ("S04","ChainStream","C1","Solana/EVM mints and transfers",DISABLED,POL_EXT,""),
 ("S05","DexScanner","C1","DEX pairs (synthetic fixture)",ENABLED,"","D3"),
 ("S06","FilingsFeed","C1","SEC filings (synthetic fixture)",ENABLED,"","D2"),
 ("S07","NewsWire","C1","News / economic calendar",DISABLED,POL_NEWS,""),
 ("S08","SocialPulse","C1","X/Telegram/Reddit velocity",DISABLED,POL_NEWS,""),
 ("S09","DataQA","C1","Dedupe, schema, gaps, clock skew",ENABLED,"","D4"),
 ("S10","FeatureForge","C2","Deterministic features",ENABLED,"","D4"),
 ("S11","VolModeler","C2","Realized vol",ENABLED,"","D4"),
 ("S12","MonteCarlo","C2","Seeded path draws for P(up)",ENABLED,"","D1"),
 ("S13","FairValue","C2","Binary fair value, edge after fees",ENABLED,"","D1"),
 ("S14","RegimeDetector","C2","Trend/chop regime tags",ENABLED,"","D4"),
 ("S15","Backtester","C2","Replay engine",ENABLED,"","D4"),
 ("S16","Calibrator","C2","Brier score",IDLE,"no resolved outcomes exist in the D1 fixture, so there is nothing real to calibrate","D1"),
 ("S17","ModelRegistry","C2","Versioned model params",ENABLED,"",""),
 ("S18","EarningsReader","C3","Transcript tone",DISABLED,POL_LLM,""),
 ("S19","InsiderAnalyst","C3","Form 4 cluster rules (synthetic fixture)",ENABLED,"","D2"),
 ("S20","FilingsAnalyst","C3","8-K red-flag rules (synthetic fixture)",ENABLED,"","D2"),
 ("S21","SectorAnalyst","C3","Regulation mapping",DISABLED,POL_LLM,""),
 ("S22","SentimentScorer","C3","Sentiment scores",DISABLED,POL_LLM,""),
 ("S23","TokenForensics","C3","Deployer/rug rules (synthetic fixture)",ENABLED,"","D3"),
 ("S24","HolderAnalyst*","C3","Holder concentration rules (synthetic)",ENABLED,"","D3"),
 ("S25","ThesisWriter*","C3","Narrative synthesis",DISABLED,POL_LLM,""),
 ("S26","MorningBrief*","C3","Deterministic brief from report data",ENABLED,"",""),
 ("S27","Sizer*","C4","Fixed-fraction sizing (Decimal)",ENABLED,"","D4"),
 ("S28","KellyCapper*","C4","Fractional Kelly cap",ENABLED,"","D1"),
 ("S29","ExposureMonitor*","C4","Gross/venue exposure",ENABLED,"","D4"),
 ("S30","LossGuard*","C4","Daily/weekly loss tracking",ENABLED,"","D4"),
 ("S31","LiquidityGate*","C4","Min liquidity check",ENABLED,"","D4"),
 ("S32","CorrelationGuard*","C4","Correlated exposure",ENABLED,"","D4"),
 ("S33","LimitsAuditor*","C4","Limits hash audit",ENABLED,"",""),
 ("S34","VetoClerk*","C4","Records vetoes to trace",ENABLED,"",""),
 ("S35","OrderRouter*","C5","Routes to paper filler",ENABLED,"","D4"),
 ("S36","PaperFiller*","C5","Book-walk fills with fees+slippage",ENABLED,"","D4"),
 ("S37","BinanceLiveExec*","C5","Live Binance orders",DISABLED,POL_LIVE,""),
 ("S38","PolymarketExec*","C5","Live Polymarket orders",NOT_APPROVED,POL_LIVE,""),
 ("S39","BrokerExec*","C5","Alpaca/IBKR orders",DISABLED,POL_LIVE,""),
 ("S40","SolanaExec*","C5","Solana swaps",NOT_APPROVED,POL_LIVE,""),
 ("S41","EVMExec*","C5","EVM swaps",DISABLED,POL_LIVE,""),
 ("S42","SlippageMonitor*","C5","Realized vs modeled slippage",ENABLED,"","D4"),
 ("S43","Settler*","C6","Position settlement",ENABLED,"","D4"),
 ("S44","PnLAccountant*","C6","Net-of-cost PnL",ENABLED,"","D4"),
 ("S45","Reconciler*","C6","Ledger vs positions",ENABLED,"","D4"),
 ("S46","WalletWatcher*","C6","Wallet balances",DISABLED,POL_LIVE,""),
 ("S47","HonestReporter*","C6","Generated honest report",ENABLED,"","D4"),
 ("S48","CostMeter*","C6","Metered compute/LLM cost",ENABLED,"",""),
 ("S49","Notifier*","C6","Telegram/Slack/email alerts",DISABLED,POL_EXT,""),
 ("S50","Archivist*","C6","Audit log export",ENABLED,"",""),
]
CREWS = {"C1":"SPOTTER","C2":"PRIOR","C3":"EDGE","C4":"KELLY","C5":"TAKER","C6":"CLOSER"}

class AgentDisabled(Exception): pass

@dataclass
class Agent:
    agent_id: str; name: str; crew: str; task: str; state: str; reason: str; desk: str
    concurrency: int = 4; sla_ms: int = 2000
    in_schema: str = "Any"; out_schema: str = "Any"
    calls: int = 0; errors: int = 0; sla_breaches: int = 0; total_ms: float = 0.0; queue: int = 0
    last_ok: float | None = None; llm_tokens: int = 0
    _sem: asyncio.Semaphore | None = field(default=None, repr=False)
    async def run(self, fn: Callable[..., Any], *a) -> Any:
        if self.state != ENABLED: raise AgentDisabled(f"{self.agent_id} {self.state}: {self.reason}")
        if self._sem is None: self._sem = asyncio.Semaphore(self.concurrency)
        self.queue += 1
        async with self._sem:
            self.queue -= 1; t = time.perf_counter()
            try:
                r = await asyncio.wait_for(asyncio.to_thread(fn, *a), self.sla_ms/1000)
                self.last_ok = time.time(); return r
            except asyncio.TimeoutError:
                self.sla_breaches += 1; self.errors += 1; raise
            except Exception:
                self.errors += 1; raise
            finally:
                self.calls += 1; self.total_ms += (time.perf_counter()-t)*1000
    def health(self) -> dict:
        if self.state != ENABLED: return {"status": self.state, "reason": self.reason}
        return {"status": "OK" if self.errors == 0 else "DEGRADED", "reason": ""}
    def metrics(self) -> dict:
        return {"id":self.agent_id,"name":self.name,"crew":self.crew,"crew_name":CREWS[self.crew],"task":self.task,
                "state":self.state,"reason":self.reason,"desk":self.desk,"concurrency":self.concurrency,"sla_ms":self.sla_ms,
                "in":self.in_schema,"out":self.out_schema,"calls":self.calls,"errors":self.errors,"sla_breaches":self.sla_breaches,
                "avg_ms": round(self.total_ms/self.calls,3) if self.calls else None,"queue":self.queue,
                "llm_tokens":self.llm_tokens,"health":self.health()["status"]}

class Registry:
    def __init__(self):
        self.agents = {s[0]: Agent(*s) for s in SPEC}
        assert len(self.agents) == 50
    def __getitem__(self, k) -> Agent: return self.agents[k]
    def all(self): return list(self.agents.values())
