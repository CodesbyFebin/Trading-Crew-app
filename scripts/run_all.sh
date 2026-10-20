#!/usr/bin/env bash
# One command: install deps, run tests, drills, paper day, then serve the app on 127.0.0.1:${PORT:-8795}.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip -q install -r requirements.txt
export LIVE_ENABLED=false
for v in CREW_APPROVAL_HMAC_KEY CREW_OWNER_TOKEN CREW_OPERATOR_TOKEN CREW_VIEWER_TOKEN; do
  if [ -z "${!v:-}" ]; then export $v="$(.venv/bin/python -c 'import secrets;print(secrets.token_hex(16))')"; GEN=1; fi
done
.venv/bin/pytest -q
.venv/bin/python scripts/run_drills.py
.venv/bin/python scripts/run_paper_day.py > /dev/null
PORT=${PORT:-8795}
echo "Viewer:   http://127.0.0.1:$PORT/?token=$CREW_VIEWER_TOKEN"
echo "Operator: http://127.0.0.1:$PORT/?token=$CREW_OPERATOR_TOKEN"
echo "Owner:    http://127.0.0.1:$PORT/?token=$CREW_OWNER_TOKEN"
[ "${GEN:-}" = 1 ] && echo "(tokens/HMAC key were generated for this session only; set them in env to persist)"
exec .venv/bin/uvicorn crew.api:app --host 127.0.0.1 --port "$PORT"
