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


def test_strict_checks_on_price_data_when_loaded(tmp_path):
    from crew.desk_d4 import s01_tape
    from crew.connectors import BinanceReplay
    # 1. Valid replay sample passes contract and s01_tape
    br = BinanceReplay()
    assert br.test()["passed"]
    ticks = s01_tape(br.path)
    assert len(ticks) == 8640

    # 2. Malformed market JSONL rows are rejected on load by s01_tape and BinanceReplay.contract
    bad_jsonl = tmp_path / "bad_tape.jsonl"
    for bad_row in [
        {"type": "market", "ts": 1000, "symbol": "BTCUSDT", "bid": "0", "ask": "100", "bids": [["99", "1"]], "asks": [["100", "1"]], "quote_volume_24h": "1000", "status": "TRADING"},
        {"type": "market", "ts": 1000, "symbol": "BTCUSDT", "bid": "100", "ask": "101", "bids": [["-1", "1"]], "asks": [["101", "1"]], "quote_volume_24h": "1000", "status": "TRADING"},
        {"type": "market", "ts": 1000, "symbol": "BTCUSDT", "bid": "100", "ask": "101", "bids": [["100", "1"]], "asks": [["101", "1"]], "quote_volume_24h": "-5", "status": "TRADING"},
        {"type": "market", "ts": 1000, "symbol": "", "bid": "100", "ask": "101", "bids": [["100", "1"]], "asks": [["101", "1"]], "quote_volume_24h": "100", "status": "TRADING"},
    ]:
        assert not br.contract(bad_row)
        bad_jsonl.write_text(json.dumps(bad_row) + "\n", encoding="utf-8")
        try:
            s01_tape(bad_jsonl)
            raise AssertionError(f"s01_tape should have rejected {bad_row}")
        except ValueError:
            pass



def test_signals_never_use_future_bars():
    from crew.desk_d4 import s01_tape, s09_dataqa, s10_features, s14_regime, Tick
    from crew.connectors import BinanceReplay
    from crew import skills as SK

    # Take first 80 BTCUSDT ticks from the replay fixture
    all_ticks = [t for t in s09_dataqa(s01_tape(BinanceReplay().path)).ticks if t.symbol == "BTCUSDT"][:80]
    full_feats = s10_features(all_ticks, fast=5, slow=15, vol_n=20)

    def d4_signals(feats):
        out = {}
        prev = None
        for idx, f in enumerate(feats):
            if prev is not None:
                if prev.ema_f <= prev.ema_s and f.ema_f > f.ema_s and s14_regime(f, D("0.0001")) == "TREND_UP":
                    out[idx] = "BUY"
                elif prev.ema_f >= prev.ema_s and f.ema_f < f.ema_s:
                    out[idx] = "SELL"
            prev = f
        return out

    full_sig = d4_signals(full_feats)
    assert all(0 <= idx < len(all_ticks) for idx in full_sig)

    # Prefix invariance proof: at any bar i, computing features and signals on prefix ticks[:i+1]
    # or on a series where all future bars ticks[i+1:] are mutated to 999,999 produces the exact same result at bar i
    for i in (15, 25, 40, 60, 79):
        prefix_ticks = all_ticks[: i + 1]
        prefix_feats = s10_features(prefix_ticks, fast=5, slow=15, vol_n=20)
        assert prefix_feats[i] == full_feats[i]

        mutated_future = prefix_ticks + [
            Tick(t.ts, t.symbol, D("999999"), D("1000000"), ((D("999999"), D("10")),), ((D("1000000"), D("10")),), t.qv24, t.status)
            for t in all_ticks[i + 1 :]
        ]
        mutated_feats = s10_features(mutated_future, fast=5, slow=15, vol_n=20)
        assert mutated_feats[i] == full_feats[i]
        assert d4_signals(prefix_feats).get(i) == full_sig.get(i) == d4_signals(mutated_feats).get(i)

    # Also verify indicator skills (sma, ema, rsi, atr) never leak future bars
    mids = [t.mid for t in all_ticks[:40]]
    highs = [t.ask for t in all_ticks[:40]]
    lows = [t.bid for t in all_ticks[:40]]
    for i in (15, 25, 39):
        mut_mids = mids[: i + 1] + [D("999999")] * (len(mids) - i - 1)
        mut_highs = highs[: i + 1] + [D("1000005")] * (len(highs) - i - 1)
        mut_lows = lows[: i + 1] + [D("999990")] * (len(lows) - i - 1)
        assert SK.sma(mids[: i + 1], 10)[i] == SK.sma(mids, 10)[i] == SK.sma(mut_mids, 10)[i]
        assert SK.ema(mids[: i + 1], 10)[i] == SK.ema(mids, 10)[i] == SK.ema(mut_mids, 10)[i]
        assert SK.rsi(mids[: i + 1], 14)[i] == SK.rsi(mids, 14)[i] == SK.rsi(mut_mids, 14)[i]
        assert SK.atr(highs[: i + 1], lows[: i + 1], mids[: i + 1], 14)[i] == SK.atr(highs, lows, mids, 14)[i] == SK.atr(mut_highs, mut_lows, mut_mids, 14)[i]
