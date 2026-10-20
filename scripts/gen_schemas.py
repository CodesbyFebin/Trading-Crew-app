"""Generate JSON Schemas (draft 2020-12) for typed models via pydantic.TypeAdapter. Run: python scripts/gen_schemas.py"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from pydantic import TypeAdapter
from crew import models, bus, connectors, desk_d4, desk_d5, jev, llm_router, memory, modes, overseer, risk, api
MODELS = {
 "Event": models.Event, "TraceRow": models.TraceRow, "RiskEvent": models.RiskEvent, "Approval": models.Approval,
 "ConfigVersion": models.ConfigVersion, "TicketState": models.TicketState, "Manifest": connectors.Manifest,
 "Tick": desk_d4.Tick, "Fill": desk_d4.Fill, "OwnerSignals": desk_d5.OwnerSignals, "JevReply": jev.JevReply,
 "AdvisoryNote": llm_router.AdvisoryNote, "Fact": memory.Fact, "Stats": modes.Stats, "GateResult": modes.GateResult,
 "Budget": overseer.Budget, "LaneResult": overseer.LaneResult, "OrderIntent": risk.OrderIntent, "Portfolio": risk.Portfolio,
 "Decision": risk.Decision, "CfgIn": api.CfgIn, "ModeIn": api.ModeIn, "KillIn": api.KillIn, "ApprIn": api.ApprIn,
 "SkillIn": api.SkillIn, "JevIn": api.JevIn,
}
def main():
    out = ROOT/"schemas"; out.mkdir(exist_ok=True); skipped = {}
    for name, t in MODELS.items():
        try: s = TypeAdapter(t).json_schema(mode="serialization")
        except Exception as e: skipped[name] = f"{type(e).__name__}: {e}"; continue
        s = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"https://codesbyfebin.github.io/Trading-Crew-app/schemas/{name}.json", **s}
        (out/f"{name}.json").write_text(json.dumps(s, indent=1) + "\n")
    print(len(MODELS) - len(skipped), "schemas;", "skipped:", skipped)
if __name__ == "__main__": main()
