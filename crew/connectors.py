"""Connector framework: one interface, manifest, health/test/contract. No network calls in this build."""
from __future__ import annotations
import abc, hashlib, json, time
from dataclasses import dataclass, asdict
from pathlib import Path
from .modes import live_enabled

FIX = Path(__file__).resolve().parent.parent / "fixtures"
class LiveDisabled(Exception): pass

@dataclass(frozen=True)
class Manifest:
    name: str; kind: str; venue: str; mode: str; live: bool; docs_verified: bool; notes: str = ""

class Connector(abc.ABC):
    manifest: Manifest
    calls = 0; errors = 0; last_latency_ms: float | None = None
    @abc.abstractmethod
    def fetch(self) -> list[dict]: ...
    @abc.abstractmethod
    def contract(self, row: dict) -> bool: ...
    def health(self) -> dict:
        t = time.perf_counter()
        try: rows = self.fetch(); ok = bool(rows)
        except LiveDisabled as e: return {"status":"DISABLED","detail":str(e)}
        except Exception as e: self.errors += 1; return {"status":"DOWN","detail":f"{type(e).__name__}: {e}"}
        finally: self.last_latency_ms = round((time.perf_counter()-t)*1000,3); self.calls += 1
        return {"status":"OK" if ok else "EMPTY","detail":f"{len(rows)} rows"}
    def test(self) -> dict:
        try: rows = self.fetch()
        except LiveDisabled as e: return {"passed":False,"detail":str(e)}
        bad = [i for i,r in enumerate(rows) if not self.contract(r)]
        return {"passed": not bad and bool(rows), "rows": len(rows), "contract_failures": len(bad)}
    def info(self): return {**asdict(self.manifest), "calls": self.calls, "errors": self.errors, "latency_ms": self.last_latency_ms}

class BinanceReplay(Connector):
    manifest = Manifest("binance-replay","market-data","binance","REPLAY",False,False,"copy of copytrader replay sample; synthetic prices")
    path = FIX/"binance_replay_sample.jsonl"
    def fetch(self): return [json.loads(l) for l in self.path.read_text().splitlines()]
    def sha256(self): return hashlib.sha256(self.path.read_bytes()).hexdigest()
    def contract(self, r):
        if r.get("type") == "leader": return {"symbol","side","notional","price"} <= r.keys()
        return (r.get("type")=="market" and {"ts","symbol","bid","ask","bids","asks","quote_volume_24h","status"} <= r.keys()
                and all(len(l)==2 for l in r["bids"]+r["asks"]))

class FixtureConnector(Connector):
    def __init__(self, name, file, key, required):
        self.manifest = Manifest(name,"fixture","synthetic","REPLAY",False,False,"SYNTHETIC FIXTURE - not real data")
        self.file, self.key, self.required = file, key, set(required)
    def fetch(self): return json.loads((FIX/self.file).read_text())[self.key]
    def contract(self, r): return self.required <= r.keys()

class LiveAdapter(Connector):
    """Present but disabled. Raises before any network code can run."""
    def __init__(self, name, venue):
        self.manifest = Manifest(name,"execution",venue,"LIVE",True,False,"disabled: live gates cannot pass in this build")
    def _guard(self):
        if not live_enabled(): raise LiveDisabled(f"{self.manifest.name}: LIVE_ENABLED=false")
        raise LiveDisabled(f"{self.manifest.name}: live promotion gates not passed (owner policy)")
    def fetch(self): self._guard(); return []
    def place_order(self, *a, **k): self._guard()
    def contract(self, r): return False

def all_connectors():
    return [BinanceReplay(),
            FixtureConnector("polymarket-fixture","d1_prediction_markets.json","markets",["id","spot","strike","yes_ask"]),
            FixtureConnector("edgar-fixture","d2_filings.json","filings",["ticker","form","text"]),
            FixtureConnector("dex-fixture","d3_tokens.json","tokens",["symbol","liquidity_usd","age_hours"]),
            LiveAdapter("binance-live","binance"), LiveAdapter("polymarket-live","polymarket"),
            LiveAdapter("alpaca-live","alpaca"), LiveAdapter("solana-live","solana")]
