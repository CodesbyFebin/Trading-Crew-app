# PyInstaller spec (onedir). Run from repo root: pyinstaller desktop/trading_crew.spec
# Bundles only tracked, non-secret files: code, web UI, config (hash-locked limits), synthetic fixtures, example reports.
import os, subprocess
REPO = os.path.abspath(os.path.join(SPECPATH, ".."))
from PyInstaller.utils.hooks import collect_submodules
tracked = subprocess.check_output(["git", "ls-files", "web", "config", "fixtures", "reports"], text=True, cwd=REPO).split()
assert not any(f.endswith((".env", ".db", ".pem", ".key")) or f.endswith("tokens.json") and not f.startswith("fixtures/") for f in tracked), "refusing to bundle secret-like files"
datas = [(os.path.join(REPO, f), f.rsplit("/", 1)[0]) for f in tracked]
hidden = collect_submodules("uvicorn") + collect_submodules("crew") + ["webview"]
a = Analysis(["launcher.py"], pathex=[REPO], datas=datas, hiddenimports=hidden,
             excludes=["pytest", "fakeredis", "redis", "tkinter"], noarchive=False)
pyz = PYZ(a.pure)
ICON = (os.path.join(REPO, "web/icons/favicon.ico") if os.path.exists(os.path.join(REPO, "web/icons/favicon.ico")) else None)
if os.environ.get("CREW_ONEFILE") == "1":   # single self-extracting executable (used for the Windows .exe)
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="trading-crew", console=True, icon=ICON)
else:                                        # onedir (used for the .deb)
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="trading-crew", console=True, icon=ICON)
    coll = COLLECT(exe, a.binaries, a.datas, name="trading-crew")
