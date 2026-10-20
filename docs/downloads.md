# Downloads

## Downloads (desktop and Android)

> **Paper only. Live trading is disabled in every build. Not financial advice.** Prices in the bundled run are a synthetic replay sample, not market data.

| Platform | Download | Checksum |
|---|---|---|
| Windows 10/11 (x64, single .exe) | [trading-crew-windows-x64.exe](https://github.com/CodesbyFebin/Trading-Crew-app/releases/download/v0.1.0/trading-crew-windows-x64.exe) | [.sha256](https://github.com/CodesbyFebin/Trading-Crew-app/releases/download/v0.1.0/trading-crew-windows-x64.exe.sha256) |
| Debian / Ubuntu (amd64) | [trading-crew-linux-amd64.deb](https://github.com/CodesbyFebin/Trading-Crew-app/releases/download/v0.1.0/trading-crew-linux-amd64.deb) | [.sha256](https://github.com/CodesbyFebin/Trading-Crew-app/releases/download/v0.1.0/trading-crew-linux-amd64.deb.sha256) |
| Android 7+ (viewer) | [trading-crew-viewer.apk](https://github.com/CodesbyFebin/Trading-Crew-app/releases/download/v0.1.0/trading-crew-viewer.apk) | [.sha256](https://github.com/CodesbyFebin/Trading-Crew-app/releases/download/v0.1.0/trading-crew-viewer.apk.sha256) |

All checksums are also in [SHA256SUMS.txt](https://github.com/CodesbyFebin/Trading-Crew-app/releases/download/v0.1.0/SHA256SUMS.txt). These links point to the **v0.1.0 pre-release** (GitHub's `releases/latest` skips pre-releases, so versioned links are used). All releases: [Releases page](https://github.com/CodesbyFebin/Trading-Crew-app/releases). Builds come from `.github/workflows/packaging.yml` on a `v*` tag, which builds, smoke-tests and attaches the files.

**Verify before running:** `sha256sum -c trading-crew-linux-amd64.deb.sha256` (Linux) or `Get-FileHash trading-crew-windows-x64.exe -Algorithm SHA256` (Windows).

**Desktop (.exe / .deb).** One bundled app: the FastAPI server plus a native window (pywebview; it falls back to your browser if no webview is available). It listens on `127.0.0.1` only, in PAPER mode, with `LIVE_ENABLED` forced to false and any LLM/DB keys from the launching shell ignored. On first run it generates random owner/operator/viewer tokens and an approval key in your per-user data folder (`%APPDATA%\TradingCrew` on Windows, `~/.local/share/trading-crew` on Linux; file mode 0600 where supported). No secrets ship inside the build. Install the .deb with `sudo apt install ./trading-crew-linux-amd64.deb`, then run `trading-crew` (`--headless` for server only).

**Android (.apk).** The trading engine does not run on the phone. The app is a thin, read-only viewer for **your own** desktop instance on your LAN: start the desktop app with `trading-crew --lan --port 8790`, get the viewer token with `trading-crew --print-viewer-token`, then enter `http://<your-PC-IP>:8790/` and that token in the app. Use only the viewer token on a phone, never the owner token. Traffic is plain HTTP on your LAN, so use a network you trust. Long-press Back to reset the connection.

**Unsigned builds.** Unless the release notes say otherwise, the .exe is not code-signed (Windows SmartScreen will warn), and the APK is a debug build or signed with the maintainer's own key (Android/Play Protect may warn about an unknown developer). Only install files whose SHA256 matches.
