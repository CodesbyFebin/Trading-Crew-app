import json
from crew.agents import ENABLED, IDLE
from crew.desks_synthetic import run_d1, run_d2, run_d3
from crew import backtest

EVENT_DRIVEN = {"S34": "only runs when the risk engine vetoes", "S15": "runs on /api/backtests/run"}
def test_every_enabled_agent_does_real_work(paper):
    reg = paper.reg
    never = {a.agent_id for a in reg.all() if a.state == ENABLED and a.calls == 0}
    assert never <= set(EVENT_DRIVEN), never
    if paper.result["D4"]["vetoes"]: assert reg["S34"].calls > 0
    assert reg["S16"].state == IDLE and reg["S16"].calls == 0 and reg["S16"].reason
    assert set(paper.result["agents_invoked"]) == {a.agent_id for a in reg.all() if a.calls}

def test_split_agents_match_reference_desks(paper):
    syn = paper.result["synthetic_desks"]
    assert [{k: v for k, v in x.items() if k != "kelly_capped"} for x in syn["D1"]] == run_d1()
    assert syn["D2"] == run_d2() and syn["D3"] == run_d3()

def test_post_run_monitors_consistent(paper):
    w, d = paper.result["agent_work"], paper.result["D4"]
    assert w["S33_limits_file_ok"] is True and w["S17_model_registry"]["matches_run"]
    if not d["open_positions_mtm"]: assert w["S44_ledger_cash_flow_check"] == d["net_pnl_after_costs"]

def test_backtester_agent_invoked():
    r = backtest.run(grid=[(20, 60, "0.0001")]); assert r["s15_calls"] == 1 and r["variants"][0]["net_pnl_after_costs"] == "-3.6518"
