"""Desktop launcher: per-user tokens with 0600 perms, stable across runs, no secrets in the repo bundle list."""
import importlib.util, json, os, stat, sys, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("launcher", ROOT/"desktop"/"launcher.py"); L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)

def test_tokens_generated_private_and_stable(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_CREW_HOME", str(tmp_path/"app"))
    d = L.data_dir(); t1 = L.load_tokens(d); t2 = L.load_tokens(d)
    assert t1 == t2 and all(len(t1[k]) >= 40 for k in L.TOKEN_KEYS) and len(set(t1.values())) == 4
    if os.name == "posix":
        assert stat.S_IMODE((d/"tokens.json").stat().st_mode) == 0o600 and stat.S_IMODE(d.stat().st_mode) == 0o700

def test_print_viewer_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRADING_CREW_HOME", str(tmp_path))
    assert L.main(["--print-viewer-token"]) == 0
    assert capsys.readouterr().out.strip() == json.loads((tmp_path/"tokens.json").read_text())["CREW_VIEWER_TOKEN"]

def test_live_flag_is_opt_in_default_and_loopback_default():
    src = (ROOT/"desktop"/"launcher.py").read_text()
    assert 'os.environ.setdefault("LIVE_ENABLED", "false")' in src
    assert '"LIVE_ENABLED"' not in src.split("STRIP =", 1)[1].split("\n", 1)[0]
    assert "venue adapter exists" in src
    assert '"0.0.0.0" if a.lan else "127.0.0.1"' in src

def test_bundle_file_list_has_no_secrets():
    files = subprocess.check_output(["git", "ls-files", "web", "config", "fixtures", "reports"], cwd=ROOT, text=True).split()
    assert files and not any(f.endswith((".env", ".db", ".pem", ".key", ".jks", ".keystore")) for f in files)
