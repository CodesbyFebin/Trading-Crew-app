"""S15 chronological replay evaluator.

The parameter grid is fixed in source before evaluation. Each variant runs independently
over non-overlapping 60/20/20 chronological windows; indicators warm up using earlier rows,
but trading is restricted to the named window. The source is synthetic and results are not
evidence of an edge or strategy approval.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

from .agents import Registry
from .connectors import BinanceReplay
from .desk_d4 import s01_tape, s09_dataqa
from .engine import CrewSystem, ROOT

GRID = [(20, 60, "0.0001"), (20, 60, "0.0005"), (10, 30, "0.0001"),
        (10, 30, "0.0005"), (30, 90, "0.0001"), (50, 200, "0.0001")]
LABEL = ("FIXED 60/20/20 chronological replay windows on synthetic sample prices; "
         "all variants shown; not evidence of edge; not a strategy approval")


def _fixed_windows() -> tuple[str, list[dict[str, int]]]:
    source = BinanceReplay()
    ticks = s09_dataqa(s01_tape(source.path)).ticks
    if not ticks:
        raise ValueError("replay source has no usable ticks")
    first, last = min(t.ts for t in ticks), max(t.ts for t in ticks)
    span = last - first
    if span < 2:
        raise ValueError("replay source is too short for chronological splits")
    train_end = first + int(span * 0.60)
    validation_end = first + int(span * 0.80)
    windows = [
        {"name": "TRAIN", "start_ts": first, "end_ts": train_end},
        {"name": "VALIDATION", "start_ts": train_end + 1, "end_ts": validation_end},
        {"name": "HOLDOUT", "start_ts": validation_end + 1, "end_ts": last},
    ]
    if any(a["end_ts"] < a["start_ts"] for a in windows):
        raise ValueError("replay source cannot form three non-empty windows")
    return source.sha256(), windows


def _fold_metrics(result: dict, window: dict) -> dict:
    d = result["D4"]
    trips = int(d["round_trips"])
    wins = int(d["winning_round_trips"])
    return {
        "window": window["name"],
        "start_ts": window["start_ts"],
        "end_ts": window["end_ts"],
        "net_pnl_after_costs": d["net_pnl_after_costs"],
        "fees_paid": d["fees_paid"],
        "fills": d["fills"],
        "round_trips": trips,
        "wins": wins,
        "win_rate": str((D(wins) / D(trips)).quantize(D("0.0001"))) if trips else None,
        "open_positions_mtm": d["open_positions_mtm"],
        "vetoes": len(d["vetoes"]),
        "drift": d["reconciliation_drift"],
        "qa": d["qa"],
    }


def run(grid=GRID) -> dict:
    source_sha256, windows = _fixed_windows()
    rows = []
    reg = Registry()
    reg["S15"].sla_ms = 60000   # one full three-window run may take several seconds
    for fast, slow, slope in grid:
        folds = []
        for window in windows:
            t0 = time.perf_counter()

            def one():
                return CrewSystem(fast=fast, slow=slow, slope=D(slope),
                                  eval_start_ts=window["start_ts"],
                                  eval_end_ts=window["end_ts"]).run_paper_day()

            result = asyncio.run(reg["S15"].run(one,))
            d = result["D4"]
            if d["source_sha256"] != source_sha256:
                raise RuntimeError("replay source changed while the walk-forward grid was running")
            fold_provenance = dict(d["provenance"])
            fold_provenance["time_range_utc"] = [
                datetime.fromtimestamp(window[key], timezone.utc).isoformat()
                for key in ("start_ts", "end_ts")
            ]
            fold_provenance["evaluation_window"] = window["name"]
            folds.append({**_fold_metrics(result, window), "provenance": fold_provenance,
                          "wall_s": round(time.perf_counter() - t0, 3)})
        rows.append({"fast": fast, "slow": slow, "slope": slope, "folds": folds})
    provenance = dict(folds[0]["provenance"]) if rows and rows[0]["folds"] else {
        "source": "fixtures/binance_replay_sample.jsonl", "source_sha256": source_sha256,
        "data_status": "SYNTHETIC_REPLAY", "verified_historical": False, "live": False,
    }
    provenance["sample"] = "synthetic chronological folds; fixed source grid; no edge claim or strategy approval"
    provenance["limitations"] = list(provenance.get("limitations", []))
    provenance["limitations"].append("the held-out timestamp slice is part of the same short synthetic fixture, not independent external validation")
    return {
        "label": LABEL,
        "provenance": provenance,
        "source_sha256": source_sha256,
        "split_method": "fixed chronological 60/20/20 by timestamp; independent fold equity; causal indicator warm-up",
        "windows": windows,
        "variants": rows,
        "variants_tried": len(rows),
        "fold_runs": sum(len(row["folds"]) for row in rows),
        "s15_calls": reg["S15"].calls,
        "interpretation": "Synthetic replay only. The parameter grid is fixed before these windows; no optimization, edge claim, or strategy approval is implied.",
    }


def save(res: dict, out=ROOT / "reports") -> Path:
    out.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    p = out / f"backtests-{ts}.json"
    payload = json.dumps(res, indent=1)
    p.write_text(payload)
    (out / "backtests-latest.json").write_text(payload)
    return p
