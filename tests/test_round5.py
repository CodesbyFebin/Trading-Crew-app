import json
from decimal import Decimal as D
from pathlib import Path
import httpx, pytest
from crew.orderbook import L2Book, BookError, StalenessGuard
from crew.llm_router import LLMRouter, cost_of, load_pricing
from crew.connectors import BinanceReplay
from crew.engine import CrewSystem
from crew.risk import utilisation, Limits, OrderIntent, Portfolio
VW = {"Authorization": "Bearer view-t"}
ROOT = Path(__file__).resolve().parent.parent

def test_l2_book_on_fixture():
    rows = [r for r in BinanceReplay().fetch() if r.get("type") == "market"][:50]
    for r in rows:
        b = L2Book.from_row(r)
        assert b.best_bid == D(str(r["bid"])) and b.best_ask == D(str(r["ask"])) and b.spread_bps() > 0
        q = b.asks[0][1] / 2; f = b.vwap_fill("BUY", q); assert f["vwap"] == b.best_ask and f["impact_bps_vs_best"] == 0
        big = b.depth("ask"); assert b.vwap_fill("BUY", big)["vwap"] >= b.best_ask
        with pytest.raises(BookError): b.vwap_fill("BUY", big + 1)
    with pytest.raises(BookError): L2Book("X", 1, ((D(10), D(1)),), ((D(9), D(1)),))     # crossed
    b = L2Book("X", 1, ((D(99), D(1)), (D(98), D(2))), ((D(101), D(1)), (D(102), D(3))))
    assert b.vwap_fill("SELL", D(2)) ["vwap"] == D("98.5") and b.depth("bid", D(150)) == D(1)

def test_staleness_guard():
    g = StalenessGuard(max_gap_s=120, max_drift_s=5)
    assert g.check("A", 1000) == (True, "OK") and g.check("A", 1060) == (True, "OK")
    assert g.check("A", 1060) == (False, "CLOCK_BACKWARDS") and g.check("A", 1300) == (False, "STALE")
    assert g.check("A", 1360, local_ts=1400.0) == (False, "CLOCK_DRIFT") and g.blocked == {"CLOCK_BACKWARDS": 1, "STALE": 1, "CLOCK_DRIFT": 1}
    assert StalenessGuard(allow_first=False).check("B", 1) == (False, "NO_REFERENCE")

def test_guard_wired_and_fixture_never_stale(paper):
    assert paper.result["feed_guard"]["blocked"] == {} and paper.result["D4"]["qa"]["gaps"] == 0

def test_guard_blocks_signal_eval_on_stale_gap(monkeypatch):
    import crew.engine as E
    orig = E.s09_dataqa
    def gappy(ticks):
        q = orig(ticks); btc = [t.ts for t in q.ticks if t.symbol == "BTCUSDT"]; hole = set(btc[100:110])   # 10-minute gap
        ks = [t for t in q.ticks if not (t.symbol == "BTCUSDT" and t.ts in hole)]
        return q.__class__(tuple(ks), q.input_rows, q.duplicates, q.crossed, q.non_trading, q.gaps, q.out_of_order)
    monkeypatch.setattr(E, "s09_dataqa", gappy)
    s = CrewSystem(); s.run_paper_day()
    assert s.result["feed_guard"]["blocked"].get("STALE", 0) >= 1 and s.telemetry["rejects"]["stale_data:STALE"] >= 1

def _tr(usage):
    return httpx.MockTransport(lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "n"}}], **({"usage": usage} if usage else {})}))
def test_metering_verified_free_price_unknown_otherwise():
    pr = load_pricing(); assert all(v["source"].startswith("https://") and v["fetched"] for v in pr.values())
    r = LLMRouter(env={"OPENROUTER_API_KEY": "k"}, transport=_tr({"prompt_tokens": 120, "completion_tokens": 30}))
    n = r.complete("JEV", [{"role": "user", "content": "q"}]); assert (n.prompt_tokens, n.completion_tokens, n.cost_usd) == (120, 30, "0")
    assert r.totals()["tokens"] == 150 and r.totals()["cost_usd"] == "0"
    r2 = LLMRouter(env={"OPENROUTER_API_KEY": "k"}, transport=_tr(None)); n2 = r2.complete("JEV", [])
    assert n2.cost_usd == "UNKNOWN" and r2.totals()["cost_usd"] == "UNKNOWN" and r2.totals()["calls_without_usage"] == 1
    r3 = LLMRouter(env={"GROQ_API_KEY": "k", "GROQ_MODEL": "some-model"}, transport=_tr({"prompt_tokens": 1, "completion_tokens": 1}))
    assert r3.complete("JEV", []).cost_usd == "UNKNOWN"          # no verified price -> never guessed
    assert cost_of({"p/m": {"prompt": "0.000001", "completion": "0.000002"}}, "p", "m", 1000, 500) == "0.002000"

def test_engine_cost_not_hardcoded(paper):
    c = paper.result["cost"]; assert c["llm_tokens"] == 0 and c["llm_cost_usd"] == "0"
    assert '"llm_cost_usd": "0.00"' not in (ROOT/"crew"/"engine.py").read_text()

def test_metrics_endpoint(client):
    assert client.get("/api/v1/metrics").status_code == 401
    r = client.get("/api/v1/metrics", headers=VW); t = r.text; assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    for name in ("crew_intents_submitted_total", "crew_rejects_total", "crew_risk_breaches_total", "crew_kill_switch_engaged",
                 "crew_signal_to_decision_seconds_bucket", "crew_quorum_outcomes_total", "crew_mode_info"):
        assert name in t, name
    s = client.get("/api/summary", headers=VW).json(); assert s["cost"]["router"]["calls"] == 0

def test_utilisation_matches_engine_breach_rule():
    L = Limits(ROOT/"config"/"limits.json")
    p = Portfolio(D(10000), D(0), {"binance": D(0)}, 0, D(0), D(0), D(10000), None)
    at = OrderIntent("t", "binance", D("200.00"), D(1), D(10**9))           # exactly 2% of equity = at limit
    assert utilisation(L, at, p)["max_position_pct"] == 1
    from crew.risk import RiskEngine
    assert not RiskEngine(L).check(at, p).approved

def test_candles_and_risk_util_api(client):
    c = client.get("/api/candles?symbol=BTCUSDT&interval=900", headers=VW).json()
    assert c["candles"] and all(D(k["low"]) <= D(k["open"]) <= D(k["high"]) for k in c["candles"]) and "synthetic" in c["label"]
    assert client.get("/api/candles?interval=5", headers=VW).status_code == 400
    u = client.get("/api/risk/utilisation", headers=VW).json(); assert u["checks"] >= 1 and "max_position_pct" in u["peak"]

def test_vendored_chart_license():
    d = ROOT/"web"/"vendor"/"lightweight-charts"
    assert (d/"LICENSE").read_text().count("Apache License") >= 1 and "TradingView" in (d/"NOTICE").read_text()
