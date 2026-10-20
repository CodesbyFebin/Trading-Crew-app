"""Research-only S63-S72 formulas: hand-checked values, registry flags, and proof they are not wired into execution."""
from decimal import Decimal as D
from pathlib import Path
import pytest
from crew import skills as SK

RO = ["freqtrade_roi_trailing","avellaneda_stoikov_mm","queue_fill_estimate","grid_dca_ladder","amm_optimal_arb_size",
      "triangular_arb_edge","binary_complement_cost","weighted_pillar_score","bellman_q_update","validate_webhook_signal"]
ROOT = Path(__file__).resolve().parent.parent

def test_flagged_research_only_and_not_wired():
    for n in RO: assert SK.REGISTRY[n].research_only, n
    assert not any(SK.REGISTRY[n].research_only for n in ("sma","position_size","reconcile"))
    assert all(c["research_only"] == (c["name"] in RO) for c in SK.catalog())
    src = "".join((ROOT/"crew"/f).read_text() for f in ("engine.py","agents.py","risk.py","modes.py","desk_d4.py","killswitch.py","drills.py"))
    for n in RO: assert n not in src, n

def test_roi_trailing():
    r = SK.freqtrade_roi_trailing(100, 101, "101.2", 15)
    assert r["pnl_bps"] == 100 and r["target_roi_bps"] == D("131.25") and r["trail_armed"]
    assert r["trail_stop_px"] == D("100.6940") and r["exit_reason"] == "HOLD"
    assert SK.freqtrade_roi_trailing(100, "100.6", "101.2", 15)["exit_reason"] == "TRAILING_STOP"
    with pytest.raises(ValueError): SK.freqtrade_roi_trailing(100, 102, 101, 1)

def test_avellaneda_stoikov():
    r = SK.avellaneda_stoikov_mm(100, 1, 2)          # r = 100 - 1*0.1*4*1 = 99.6
    assert r["reservation_px"] == D("99.6")
    assert abs(r["spread"] - (D("0.4") + 20 * D("0.064538521137571"))) < D("1e-12")   # 20*ln(16/15)
    assert abs((r["ask_px"] + r["bid_px"]) / 2 - D("99.6")) < D("1e-20")

def test_queue_fill():
    r = SK.queue_fill_estimate(10, 8, "0.5", 4)      # depletion 13 -> 3 of 4 filled
    assert r == {"remaining_queue_ahead": 0, "filled_qty": 3, "fill_fraction": D("0.75")}
    assert SK.queue_fill_estimate(10, 5)["fill_fraction"] == 0

def test_grid():
    g = SK.grid_dca_ladder(100, "0.04", 2, 2)
    assert [x["price"] for x in g["buy"]] == [98, 96] and [x["price"] for x in g["sell"]] == [102, 104]
    assert abs(g["buy"][0]["weight"] - D(1)/3) < D("1e-20") and abs(sum(x["weight"] for x in g["buy"]) - 1) < D("1e-20")

def test_amm_matches_brute_force():
    r = SK.amm_optimal_arb_size(1000, 2000, 1000, 1000, 0)   # x* = (sqrt(2e12)-1e6)/3000 = 138.0712...
    assert abs(r["optimal_input_a"] - D("138.0711874576983")) < D("1e-9")
    for fee in (0, 30):
        x = SK.amm_optimal_arb_size(1000, 2000, 1000, 1000, fee)["optimal_input_a"]; g = 1 - D(fee)/10000
        def prof(i): ob = 2000*g*i/(1000+g*i); return 1000*g*ob/(1000+g*ob) - i
        best = max((D(i)/10 for i in range(1, 5000)), key=prof)
        assert abs(x - best) < D("0.11") and prof(x) >= prof(best) - D("1e-9")
    assert SK.amm_optimal_arb_size(1000, 1000, 1000, 1000, 30)["profit_a"] == 0

def test_triangular_binary_pillar_bellman():
    assert abs(SK.triangular_arb_edge("1.01", 1, 1, 10)["net_edge_bps"] - D("69.7302899")) < D("1e-9")
    b = SK.binary_complement_cost("0.52", "0.45"); assert b["edge_per_pair"] == D("0.03") and "not riskless" in b["note"]
    assert SK.weighted_pillar_score(1, 0, 0, 0, "0.5")["score"] == D("0.15")
    q = SK.bellman_q_update("0.12", "0.04", "0.18", "0.1", "0.95")
    assert q["td_error"] == D("0.091") and q["q_updated"] == D("0.1291")

def test_webhook_fail_closed():
    p = {"symbol": "BTCUSDT", "side": "buy", "ts": 1000, "source": "tv"}
    assert SK.validate_webhook_signal(p, 1030)["valid"]
    assert SK.validate_webhook_signal(p, 1061)["reason"] == "STALE_OR_FUTURE"
    assert SK.validate_webhook_signal({**p, "ts": "x"}, 1000)["reason"] == "BAD_TIMESTAMP"
    assert SK.validate_webhook_signal({"symbol": "X"}, 1000)["reason"] == "MISSING_FIELDS"
    with pytest.raises(TypeError): SK.validate_webhook_signal(p)   # no default clock
