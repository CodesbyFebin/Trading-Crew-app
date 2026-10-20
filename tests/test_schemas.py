import json
from decimal import Decimal as D
from pathlib import Path
import pytest
jsonschema = pytest.importorskip("jsonschema")
from pydantic import TypeAdapter
from crew import models, memory, risk, desk_d5, connectors, llm_router
import scripts.gen_schemas as G
SD = Path(__file__).resolve().parent.parent / "schemas"

def check(name, obj):
    s = json.loads((SD/f"{name}.json").read_text()); jsonschema.Draft202012Validator.check_schema(s)
    jsonschema.validate(TypeAdapter(type(obj)).dump_python(obj, mode="json"), s, cls=jsonschema.Draft202012Validator)

def test_all_schemas_valid_2020_12_and_current():
    files = sorted(SD.glob("*.json")); assert len(files) == len(G.MODELS)
    for f in files:
        s = json.loads(f.read_text()); assert s["$schema"].endswith("2020-12/schema")
        jsonschema.Draft202012Validator.check_schema(s)
        cur = TypeAdapter(G.MODELS[f.stem]).json_schema(mode="serialization")
        assert {k: v for k, v in s.items() if k not in ("$schema", "$id")} == cur, f"{f.name} stale: run scripts/gen_schemas.py"

def test_sample_payloads_validate():
    check("Event", models.Event("binance-replay", "tick", {"symbol": "BTCUSDT"}, "k1"))
    check("RiskEvent", models.RiskEvent("VETO", "t1", "min liquidity breached"))
    check("Fact", memory.Fact("S45", "recon", "drift 0", "metric", "paper-run"))
    check("OrderIntent", risk.OrderIntent("t1", "binance", D("150.00"), D("0.5"), D("1500000000")))
    check("OwnerSignals", desk_d5.OwnerSignals())
    check("Manifest", connectors.BinanceReplay.manifest)
    check("AdvisoryNote", llm_router.AdvisoryNote("text", "openrouter", "m:free", 12.0))

def test_invalid_payload_rejected():
    s = json.loads((SD/"Fact.json").read_text())
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate({"agent_id": "S01"}, s)
    s = json.loads((SD/"ApprIn.json").read_text())
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate({"subject": 5}, s)
