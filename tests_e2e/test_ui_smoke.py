"""Playwright smoke test: every page loads with no console/page errors. Run with a Python that has playwright:
   /workspace/.pwvenv/bin/python -m pytest tests_e2e   (CREW_PY = interpreter with the app deps, default .venv/bin/python)"""
import os, socket, subprocess, sys, time, urllib.request
from pathlib import Path
import pytest
pw = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parent.parent
PAGES = ['Control Room','Command Center','Reactor','Floor','Crew Pool','Tickets & Trace','Markets','Research','India D5','Risk Console',
         'Connectors','Approvals','Reports','Backtests','Memory','Skills','LLM Routing','JEV']
TOK = "e2e-viewer-token"

@pytest.fixture(scope="module")
def server():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "LIVE_ENABLED": "false", "CREW_VIEWER_TOKEN": TOK, "CREW_OWNER_TOKEN": "e2e-owner", "CREW_OPERATOR_TOKEN": "e2e-op",
           "CREW_APPROVAL_HMAC_KEY": "e2e-only", "CREW_MEMORY_PATH": ":memory:"}
    for k in ("OPENROUTER_API_KEY","KILOCODE_API_KEY","GROQ_API_KEY","CLINE_API_KEY","DATABASE_URL"): env.pop(k, None)
    py = os.environ.get("CREW_PY", str(ROOT/".venv"/"bin"/"python"))
    p = subprocess.Popen([py, "-m", "uvicorn", "crew.api:app", "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}/"
    for _ in range(120):
        try: urllib.request.urlopen(base, timeout=1); break
        except Exception: time.sleep(0.5)
    yield base
    p.terminate(); p.wait(10)

def test_login_required_and_url_token_ignored(server):
    with pw.sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(); pg.goto(server + f"?token={TOK}"); pg.wait_for_selector("#tk")
        assert "token=" not in pg.url; b.close()

@pytest.mark.parametrize("name", PAGES)
def test_page_loads_without_errors(server, name):
    errs = []
    with pw.sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1400, "height": 900})
        pg.add_init_script(f"sessionStorage.tok={TOK!r}")
        pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
        pg.goto(server + "#" + name); pg.wait_for_function("document.querySelector('#page section')", timeout=15000)
        pg.wait_for_timeout(500)
        assert pg.locator("#tk").count() == 0 and not errs, errs
        b.close()
