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

def test_sphere_skin_renders_real_numbers(server):
    with pw.sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1680, "height": 1050}); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(server); pg.wait_for_selector("#tk"); pg.fill("#tk", TOK); pg.click("#tb")
        pg.wait_for_selector(".skb[data-skin=sphere]"); pg.click(".skb[data-skin=sphere]"); pg.wait_for_selector(".sph .sphbig")
        assert pg.inner_text(".sphbig") == "24" and "34 STATES" in pg.inner_text(".sphlbl")
        assert "PAPER ONLY" in pg.inner_text(".sph") and "-3.6518" in pg.inner_text(".sphflows")
        txt1 = pg.eval_on_selector(".sph", "e=>{const k=e.cloneNode(true);k.querySelector('#crclock').remove();return k.textContent}")
        pg.wait_for_timeout(2000)
        txt2 = pg.eval_on_selector(".sph", "e=>{const k=e.cloneNode(true);k.querySelector('#crclock').remove();return k.textContent}")
        import difflib; assert txt1 == txt2, list(difflib.unified_diff(txt1.splitlines(), txt2.splitlines(), lineterm=""))[:12]
        pg.reload(); pg.wait_for_selector(".sph .sphbig")   # skin persisted in localStorage
        pg.click(".skb[data-skin=classic]"); pg.wait_for_selector(".crticker")
        assert not errs, errs; b.close()

def _login(pg, server):
    pg.goto(server); pg.wait_for_selector("#tk"); pg.fill("#tk", TOK); pg.click("#tb")

def test_grok_desk_default_real_numbers_and_theme(server):
    with pw.sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1680, "height": 1050}); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e))); _login(pg, server); pg.wait_for_selector(".gd .gdbig")   # default skin
        t = pg.inner_text(".gd")
        assert "9996.3482" in t and "-3.6518" in t and "2/12" in t and "PAPER ONLY" in t and "LIVE ORDERS DISABLED" in t
        assert pg.locator(".gdcrew").count() == 6 and "NO DATA" in pg.inner_text(".gdbot")
        snap = "e=>{const k=e.cloneNode(true);k.querySelector('#crclock').remove();return k.textContent}"
        a = pg.eval_on_selector(".gd", snap); pg.wait_for_timeout(2000); assert a == pg.eval_on_selector(".gd", snap)
        pg.click("#gdth"); pg.wait_for_selector(".gd.dark"); pg.reload(); pg.wait_for_selector(".gd.dark")      # theme persisted
        pg.click(".gdcrew >> nth=0"); pg.wait_for_function("location.hash.includes('Crew')")
        assert not errs, errs; b.close()

@pytest.mark.parametrize("skin", ["grokdesk", "sphere", "classic"])
def test_mobile_no_horizontal_scroll(server, skin):
    with pw.sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 390, "height": 844})
        pg.goto(server); pg.evaluate(f"localStorage.crSkin='{skin}'"); _login(pg, server)
        pg.wait_for_selector({"grokdesk": ".gdbig", "sphere": ".sphbig", "classic": ".crticker"}[skin]); pg.wait_for_timeout(800)
        sw = pg.evaluate("document.documentElement.scrollWidth"); assert sw <= 390, sw
        b.close()
