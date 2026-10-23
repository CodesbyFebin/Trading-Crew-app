"""Trading Crew desktop launcher.

Starts the bundled FastAPI app on 127.0.0.1 (never 0.0.0.0 unless --lan is given) and opens it in a native
window (pywebview) or the system browser. Live order execution is unavailable until a venue adapter exists.

Tokens: on first run, random owner/operator/viewer tokens and an approval HMAC key are generated into the
per-user app-data directory (file mode 0600 where the OS supports it). Nothing secret ships inside the build.
"""
from __future__ import annotations
import argparse, json, os, secrets, socket, sys, threading, time, urllib.request, webbrowser
from pathlib import Path

APP = "TradingCrew"
TOKEN_KEYS = ("CREW_OWNER_TOKEN", "CREW_OPERATOR_TOKEN", "CREW_VIEWER_TOKEN", "CREW_APPROVAL_HMAC_KEY")
# Never inherit database or LLM credentials from the launching shell. The live-mode flag is an explicit
# opt-in, but does not enable execution without a configured adapter and passing promotion gates.
STRIP = ("DATABASE_URL", "REDIS_URL", "OPENROUTER_API_KEY", "KILOCODE_API_KEY", "GROQ_API_KEY", "CLINE_API_KEY")

def data_dir() -> Path:
    if os.environ.get("TRADING_CREW_HOME"): d = Path(os.environ["TRADING_CREW_HOME"])
    elif sys.platform == "win32": d = Path(os.environ.get("APPDATA", Path.home())) / APP
    elif sys.platform == "darwin": d = Path.home() / "Library" / "Application Support" / APP
    else: d = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "trading-crew"
    d.mkdir(parents=True, exist_ok=True)
    try: os.chmod(d, 0o700)
    except OSError: pass
    return d

def load_tokens(d: Path) -> dict:
    f = d / "tokens.json"
    if f.exists():
        t = json.loads(f.read_text())
        if all(t.get(k) for k in TOKEN_KEYS): return t
    t = {k: secrets.token_urlsafe(32) for k in TOKEN_KEYS}
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh: json.dump(t, fh, indent=1)
    try: os.chmod(f, 0o600)
    except OSError: pass
    return t

def free_port(host: str) -> int:
    s = socket.socket(); s.bind((host, 0)); p = s.getsockname()[1]; s.close(); return p

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="trading-crew", description="Trading Crew (live execution requires a configured venue adapter)")
    ap.add_argument("--headless", action="store_true", help="run the server only (no window/browser)")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--lan", action="store_true", help="bind 0.0.0.0 so a phone on your LAN can connect (viewer token required)")
    ap.add_argument("--print-viewer-token", action="store_true", help="print the local viewer token (for the Android client) and exit")
    a = ap.parse_args(argv)
    d = data_dir(); tok = load_tokens(d)
    if a.print_viewer_token: print(tok["CREW_VIEWER_TOKEN"]); return 0
    for k in STRIP: os.environ.pop(k, None)
    os.environ.update(tok); os.environ.setdefault("LIVE_ENABLED", "false")
    os.environ.setdefault("CREW_MEMORY_PATH", str(d / "shared_memory.db"))
    host = "0.0.0.0" if a.lan else "127.0.0.1"; port = a.port or free_port("127.0.0.1")
    import uvicorn
    from crew.api import app
    srv = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    url = f"http://127.0.0.1:{port}/"
    print(f"Trading Crew on {host}:{port}  data dir: {d}", flush=True)
    if a.headless: srv.run(); return 0
    th = threading.Thread(target=srv.run, daemon=True); th.start()
    for _ in range(240):
        try: urllib.request.urlopen(url + "health/live", timeout=1); break
        except Exception: time.sleep(0.25)
    # The UI keeps its token in sessionStorage; hand it over via an init script, never in the URL.
    js = f"TOK={json.dumps(tok['CREW_VIEWER_TOKEN'])};sessionStorage.tok=TOK;"
    try:
        import webview
        w = webview.create_window("Trading Crew", url, width=1600, height=1000)
        w.events.loaded += lambda: (w.evaluate_js(js + "render()"))
        webview.start()
    except Exception as e:
        print(f"native window unavailable ({type(e).__name__}); opening browser. Sign in with the viewer token from {d/'tokens.json'}", flush=True)
        webbrowser.open(url); th.join()
    srv.should_exit = True; return 0

if __name__ == "__main__":
    raise SystemExit(main())
