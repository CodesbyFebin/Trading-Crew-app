#!/usr/bin/env bash
# Build dist/trading-crew_<ver>_amd64.deb from the PyInstaller onedir bundle. Usage: desktop/build_deb.sh [python]
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${1:-python3}; VER=${CREW_VERSION:-0.1.0}; ARCH=$(dpkg --print-architecture 2>/dev/null || echo amd64)
rm -rf build/pyi dist/trading-crew dist/deb
"$PY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyi desktop/trading_crew.spec
R=dist/deb/trading-crew_${VER}_${ARCH}
mkdir -p "$R/DEBIAN" "$R/opt" "$R/usr/bin" "$R/usr/share/applications" "$R/usr/share/icons/hicolor/512x512/apps"
cp -a dist/trading-crew "$R/opt/trading-crew"
ln -s /opt/trading-crew/trading-crew "$R/usr/bin/trading-crew"
cp web/icons/icon-512.png "$R/usr/share/icons/hicolor/512x512/apps/trading-crew.png"
cat > "$R/usr/share/applications/trading-crew.desktop" <<D
[Desktop Entry]
Name=Trading Crew
Comment=Trading research and dashboard. Live execution requires a configured venue adapter. Not financial advice.
Exec=trading-crew
Icon=trading-crew
Terminal=false
Type=Application
Categories=Office;Finance;
D
cat > "$R/DEBIAN/control" <<C
Package: trading-crew
Version: $VER
Architecture: $ARCH
Maintainer: CodesbyFebin <CodesbyFebin@users.noreply.github.com>
Section: misc
Priority: optional
Recommends: libwebkit2gtk-4.1-0 | libwebkit2gtk-4.0-37, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0, python3-gi
Description: Trading Crew - multi-agent trading research app
 Runs locally on 127.0.0.1. Live execution requires a configured venue adapter and passing promotion gates.
 Tokens are generated per user on first run in ~/.local/share/trading-crew (mode 0600).
 Prices are a synthetic replay sample. Not financial advice.
C
dpkg-deb --root-owner-group --build "$R" "dist/trading-crew_${VER}_${ARCH}.deb"
( cd dist && sha256sum "trading-crew_${VER}_${ARCH}.deb" > "trading-crew_${VER}_${ARCH}.deb.sha256" )
echo "built dist/trading-crew_${VER}_${ARCH}.deb"
