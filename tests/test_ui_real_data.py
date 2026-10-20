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
    assert "PAPER ONLY" in (WEB / "index.html").read_text() and "PAPER ONLY" in (WEB / "control_room.js").read_text()
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
