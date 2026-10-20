"""S15 Backtester: replays the full D4 pipeline (agents, quorum, risk engine, paper fills) over a small fixed
parameter grid on the replay sample. IN-SAMPLE on a synthetic sample: results are NOT evidence of an edge,
every variant tried is reported (no cherry-picking)."""
from __future__ import annotations
import json, time
from decimal import Decimal as D
from pathlib import Path
import asyncio
from .agents import Registry
from .engine import CrewSystem, ROOT

GRID = [(20, 60, "0.0001"), (20, 60, "0.0005"), (10, 30, "0.0001"), (10, 30, "0.0005"), (30, 90, "0.0001"), (50, 200, "0.0001")]
LABEL = "IN-SAMPLE replay on synthetic sample prices; all variants shown; not evidence of edge; not a strategy approval"

def run(grid=GRID) -> dict:
    rows = []; reg = Registry(); reg["S15"].sla_ms = 60000   # a full replay takes ~1-2 s
    def one(fast, slow, slope): return CrewSystem(fast=fast, slow=slow, slope=D(slope)).run_paper_day()
    for fast, slow, slope in grid:
        t = time.perf_counter(); r = asyncio.run(reg["S15"].run(one, fast, slow, slope)); d = r["D4"]
        rows.append({"fast": fast, "slow": slow, "slope": slope, "net_pnl_after_costs": d["net_pnl_after_costs"],
                     "fees_paid": d["fees_paid"], "fills": d["fills"], "round_trips": d["round_trips"],
                     "wins": d["winning_round_trips"], "vetoes": len(d["vetoes"]), "drift": d["reconciliation_drift"],
                     "wall_s": round(time.perf_counter()-t, 3)})
    return {"label": LABEL, "source_sha256": d["source_sha256"], "variants": rows, "variants_tried": len(rows), "s15_calls": reg["S15"].calls}

def save(res: dict, out=ROOT/"reports") -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S"); p = out/f"backtests-{ts}.json"; p.write_text(json.dumps(res, indent=1))
    (out/"backtests-latest.json").write_text(json.dumps(res, indent=1)); return p
