#!/usr/bin/env bash
# One command: install deps, run tests, drills, paper day, then serve the app on 127.0.0.1:${PORT:-8795}.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip -q install -r requirements.txt
export LIVE_ENABLED="${LIVE_ENABLED:-false}"
for v in CREW_APPROVAL_HMAC_KEY CREW_OWNER_TOKEN CREW_OPERATOR_TOKEN CREW_VIEWER_TOKEN; do
  if [ -z "${!v:-}" ]; then export $v="$(.venv/bin/python -c 'import secrets;print(secrets.token_hex(16))')"; GEN=1; fi
done
.venv/bin/pytest -q
.venv/bin/python scripts/run_drills.py
.venv/bin/python scripts/run_paper_day.py > /dev/null
.venv/bin/python scripts/run_backtests.py > /dev/null
PORT=${PORT:-8795}
umask 077; mkdir -p var
[ "${GEN:-}" = 1 ] && printf 'CREW_VIEWER_TOKEN=%s\nCREW_OPERATOR_TOKEN=%s\nCREW_OWNER_TOKEN=%s\n' "$CREW_VIEWER_TOKEN" "$CREW_OPERATOR_TOKEN" "$CREW_OWNER_TOKEN" > var/session.env
echo "Open http://127.0.0.1:$PORT/ and sign in with your token (generated ones are in var/session.env mode 600, gitignored). Tokens are not printed or put in URLs."
exec .venv/bin/uvicorn crew.api:app --host 127.0.0.1 --port "$PORT"
