"""Builds docs/*.md from README.md sections (single source of truth) and copies schemas into docs/schemas."""
import re, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; D = ROOT/"docs"
readme = (ROOT/"README.md").read_text()
secs = {m.group(1): m for m in re.finditer(r"^## (.+)$", readme, re.M)}
def sec(title):
    m = secs[title]; nxt = [x.start() for x in secs.values() if x.start() > m.start()]
    return readme[m.start(): min(nxt) if nxt else len(readme)].replace("---\n", "").strip() + "\n"
def fix(t): return t.replace("](schemas/)", "](schemas.md)").replace("](reports/AUDIT.md)", "](https://github.com/CodesbyFebin/Trading-Crew-app/blob/main/reports/AUDIT.md)") \
    .replace("](CONTRIBUTING.md)", "](https://github.com/CodesbyFebin/Trading-Crew-app/blob/main/CONTRIBUTING.md)") \
    .replace("](AGENTS.md)", "](https://github.com/CodesbyFebin/Trading-Crew-app/blob/main/AGENTS.md)") \
    .replace("](SECURITY.md)", "](https://github.com/CodesbyFebin/Trading-Crew-app/blob/main/SECURITY.md)") \
    .replace("](CODE_OF_CONDUCT.md)", "](https://github.com/CodesbyFebin/Trading-Crew-app/blob/main/CODE_OF_CONDUCT.md)") \
    .replace("](LICENSE)", "](https://github.com/CodesbyFebin/Trading-Crew-app/blob/main/LICENSE)")
pages = {
 "index.md": ("Trading Crew (paper only)", [readme.split("## Table of contents")[0].split("\n",1)[1], "![Command Center](assets/command_center.png)\n", sec("What this is (and is not)"), sec("Disclaimers")]),
 "architecture.md": ("Architecture", [sec("Mode ladder"), sec("Desks"), sec("Trading skills catalog"), sec("Shared memory"), sec("Project layout")]),
 "safety.md": ("Safety", [sec("Safety architecture"), "![Risk Console](assets/risk_console.png)\n", sec("Testing and drills"), sec("Audit summary and known limitations")]),
 "agents.md": ("Agents", ["![Crew Pool](assets/crew_pool.png)\n", sec("The 50 agents"), sec("Model router (advisory only)"), sec("JEV, the advisory assistant"), "![JEV](assets/jev.png)\n"]),
 "api.md": ("API", [sec("API reference")]),
 "deployment.md": ("Deployment", [sec("Quickstart"), sec("Configuration and environment variables")]),
 "results.md": ("Reference results", [sec("Reference results (synthetic data)")]),
}
for f, (title, parts) in pages.items():
    (D/f).write_text(f"# {title}\n\n" + fix("\n".join(parts)))
sd = D/"schemas"; shutil.rmtree(sd, ignore_errors=True); shutil.copytree(ROOT/"schemas", sd)
names = sorted(p.stem for p in sd.glob("*.json"))
(D/"schemas.md").write_text("# JSON Schemas\n\nDraft 2020-12 schemas generated from the typed models by `scripts/gen_schemas.py` "
    "and validated by `tests/test_schemas.py`. Each one is published at `schemas/<Name>.json` on this site.\n\n" +
    "\n".join(f"- [{n}](schemas/{n}.json)" for n in names) + f"\n\n{len(names)} schemas in total.\n")
print("pages:", len(pages)+1, "schemas:", len(names))
