import json, sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crew.drills import run_all
res = run_all(); out = Path(__file__).resolve().parent.parent/"reports"; out.mkdir(exist_ok=True)
stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5,minutes=30))).strftime("%Y%m%d-%H%M%S")
(out/f"drills-{stamp}.json").write_text(json.dumps(res, indent=2, default=str))
md = [f"# Drill report {stamp} (local box time, IST)", "", "Real outputs from crew/drills.py. No live venues, no keys.", ""]
for k,v in res.items():
    md += [f"## {k}: {'PASS' if v['passed'] else 'FAIL'}", "```json", json.dumps(v, indent=2, default=str), "```", ""]
(out/f"drills-{stamp}.md").write_text("\n".join(md)); (out/"drills-latest.json").write_text(json.dumps(res, indent=2, default=str))
for k,v in res.items(): print(k, "PASS" if v["passed"] else "FAIL")
sys.exit(0 if all(v["passed"] for v in res.values()) else 1)
