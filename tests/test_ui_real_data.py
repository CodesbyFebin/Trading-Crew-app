"""Control Room UI must render only real API data: no randoms, no invented series, no CDNs; new endpoints return run data."""
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
VW = {"Authorization": "Bearer view-t"}

def test_control_room_js_has_no_fake_data_sources():
    js = (WEB / "control_room.js").read_text()
    for pat in (r"Math\.random", r"Math\.sin", r"Math\.cos", r"setInterval", r"crypto\.getRandomValues", r"performance\.now"):
        assert not re.search(pat, js), pat
    assert "NO DATA" in js

def test_no_random_and_no_cdn_anywhere_in_ui():
    for f in list(WEB.glob("*.js")) + list(WEB.glob("*.html")):
        t = f.read_text()
        assert "Math.random" not in t, f.name
        assert not re.search(r"(src|href)=[\"']https?://", t), f.name
        assert not re.search(r"fetch\([\"']https?://", t), f.name
    assert "global-market-status" in (WEB / "index.html").read_text()
    assert "global-execution-status" in (WEB / "index.html").read_text()
    assert "api('execution/status')" in (WEB / "control_room.js").read_text()
    assert "api('execution/gates')" in (WEB / "app.js").read_text()
    assert "PAPER ORDERS ONLY" not in (WEB / "index.html").read_text()
    js = (WEB / "control_room.js").read_text()
    for banned in ("NIFTY", "BANKNIFTY", "-FUT", "memecoin", "SOL-USDC"): assert banned not in js, banned

def test_book_and_pipeline_endpoints(client):
    b = client.get("/api/book?symbol=BTCUSDT", headers=VW).json()
    assert b["bids"] and b["asks"] and float(b["bids"][0][0]) < float(b["asks"][0][0]) and "synthetic" in b["label"]
    assert client.get("/api/book?symbol=NOPE", headers=VW).status_code == 404
    assert client.get("/api/book").status_code == 401
    p = client.get("/api/pipeline", headers=VW).json()
    st = {s["stage"]: s for s in p["stages"]}
    assert st["FILL"]["detail"] == "24 paper fills" and st["RECONCILE"]["status"] == "OK" and st["KILL"]["status"] == ("ENGAGED" if client.get("/api/risk", headers=VW).json()["kill"]["engaged"] else "ARMED")
    assert p["last_decision"]["agent"] == "MAIN"

def test_execution_status_reports_real_configuration_not_mode_flag(client, monkeypatch):
    monkeypatch.setenv("LIVE_ENABLED", "true")
    r = client.get("/api/execution/status", headers=VW)
    assert r.status_code == 200
    body = r.json()
    assert body["live_enabled_flag"] is True
    assert body["venue_client_configured"] is False
    assert body["account_authenticated"] is False
    assert body["order_submission_available"] is False
    assert "client" in body["reason"]

def test_execution_gates_are_backend_computed_and_fail_closed(client):
    r = client.get("/api/execution/gates", headers=VW)
    assert r.status_code == 200
    body = r.json()
    by_id = {gate["id"]: gate for gate in body["gates"]}
    assert body["promotion_allowed"] is False
    assert body["order_submission_available"] is False
    assert by_id["strategy_validation"]["status"] == "NOT_PASSED"
    assert by_id["testnet_adapter_contract"]["status"] == "PASS_LOCAL_ONLY"
    assert by_id["account_authentication"]["status"] == "NOT_CONFIGURED"
    assert by_id["live_order_adapter"]["status"] == "NOT_IMPLEMENTED"
    assert by_id["exchange_reconciliation_and_kill"]["status"] == "NOT_TESTED"
    assert by_id["local_risk_drills"]["status"] in {"PASS_LOCAL_ONLY", "NOT_PASSED"}

def test_sphere_skin_real_data_only():
    js = (WEB / "sphere.js").read_text()
    for pat in (r"Math\.random", r"setInterval", r"setTimeout", r"crypto\.getRandomValues", r"fillText", r"strokeText"):
        assert not re.search(pat, js), pat
    # the animation loop must never touch DOM text: only canvas drawing happens inside frame()
    loop = js[js.index("const frame="):]
    for pat in (r"textContent", r"innerHTML", r"innerText", r"outerHTML"):
        assert not re.search(pat, loop), pat
    assert "NO DATA" in js and "api('execution/status')" in js and "EXECUTION NOT CONFIGURED" in js and "prefers-reduced-motion" in js and 'aria-hidden="true"' in js
    assert "PAPER ONLY" not in js and "LIVE ORDERS DISABLED" not in js
    for banned in ("NIFTY", "BANKNIFTY", "-FUT", "memecoin", "SOL-USDC"): assert banned not in js, banned
    assert "sphere.js" in (WEB / "index.html").read_text()
    assert (WEB / "fonts" / "VT323-OFL.txt").exists() and not re.search(r"url\([\"']?https?://", (WEB / "app.css").read_text())

def test_grok_desk_real_data_only():
    js = (WEB / "grokdesk.js").read_text()
    for pat in (r"Math\.random", r"setInterval", r"setTimeout", r"crypto\.getRandomValues", r"fillText", r"strokeText", r"cdn", r"https?://",
                r"NIFTY", r"-FUT", r"[Mm]emecoin", r"S6[3-9]", r"S7[0-2]", r"102x", r"cheaper", r"ROI"):
        assert not re.search(pat, js), pat
    loop = js[js.index("const frame="):]
    for pat in (r"textContent", r"innerHTML", r"innerText", r"outerHTML"): assert not re.search(pat, loop), pat
    for need in ("NO DATA", "api('execution/status')", "EXECUTION NOT CONFIGURED", "prefers-reduced-motion", 'aria-hidden="true"', "synthetic replay sample", "THE PRICER", "api('book"):
        assert need in js, need
    assert "PAPER ONLY" not in js and "LIVE ORDERS DISABLED" not in js
    assert "grokdesk.js" in (WEB / "index.html").read_text()
    assert "crSkin||'grokdesk'" in (WEB / "sphere.js").read_text()   # GROK DESK is the default skin
    assert "prefers-reduced-motion" in (WEB / "app.css").read_text()
