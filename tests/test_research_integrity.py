"""Priority 5: provenance everywhere, assumptions labelled, no-lookahead / prefix invariance of the signals used,
run-scoped analytics under concurrency."""
import threading
from decimal import Decimal as D
from crew import drills
from crew.connectors import BinanceReplay
from crew.desk_d4 import s01_tape, s09_dataqa, s10_features, s14_regime
from crew.engine import CrewSystem
from crew.store import SQLiteStore
VW = {"Authorization": "Bearer view-t"}

def test_provenance_in_result_and_api(client, paper):
    p = paper.result["D4"]["provenance"]
    assert p["data_status"] == "SYNTHETIC_REPLAY" and p["verified_historical"] is False and p["live"] is False
    assert p["assumptions"]["fee_rate"].startswith("ASSUMED")
    assert p["assumptions"]["funding"].startswith("NOT MODELLED") and len(p["time_range_utc"]) == 2 and p["limitations"]
    for path in ("/api/summary", "/api/pnl", "/api/markets", "/api/candles", "/api/book"):
        assert client.get(path, headers=VW).json()["provenance"]["data_status"] == "SYNTHETIC_REPLAY", path

def test_honest_summary_never_claims_edge(paper):
    assert paper.result["honest_summary"]["claims_edge"] is False and "synthetic" in paper.result["brief"].lower()

def _ticks(): return list(s09_dataqa(s01_tape(BinanceReplay().path)).ticks)

def test_features_prefix_invariant_and_no_lookahead():
    ticks = _ticks(); full = s10_features(ticks)
    for n in (61, 500, 2000, len(ticks) // 2):
        assert s10_features(ticks[:n]) == full[:n], n                  # prefix invariance
    # perturb the FUTURE: features up to k must not change
    k = 1500; fut = [t.__class__(t.ts, t.symbol, t.bid * 2, t.ask * 2, t.bids, t.asks, t.qv24, t.status) for t in ticks[k:]]
    assert s10_features(ticks[:k] + fut)[:k] == full[:k]
    assert [s14_regime(f) for f in s10_features(ticks[:k])] == [s14_regime(f) for f in full[:k]]

def test_concurrent_killed_and_normal_runs_stay_isolated(tmp_path):
    db = str(tmp_path/"shared.db"); out = {}
    def normal(): s = CrewSystem(store=SQLiteStore(db)); out["n"] = (s, s.run_paper_day())
    def killed(): out["k"] = drills.run_with_forced_daily_loss(2, store=SQLiteStore(db))
    th = [threading.Thread(target=normal), threading.Thread(target=killed)]; [t.start() for t in th]; [t.join() for t in th]
    (sn, rn), (sk, rk) = out["n"], out["k"]
    assert rn["D4"]["net_pnl_after_costs"] == "-3.6518" and rn["D4"]["fills"] == 24 and not sn.kill.engaged
    assert sk.kill.engaged and len([r for r in sk.store.rows("ledger") if r[4] == "BUY"]) == 2
    for s, r in ((sn, rn), (sk, rk)):
        assert D(r["D4"]["reconciliation_drift"]) == 0 and len(s.store.rows("ledger")) == r["D4"]["fills"]
        assert D(r["agent_work"]["S44_ledger_cash_flow_check"]) == s.store.net_pnl("PAPER").quantize(D("0.0001"))
    assert not [x for x in sn.store.rows("audit_log") if x[3] == "kill"]        # the other run's kill never leaks
