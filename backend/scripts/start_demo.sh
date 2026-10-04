#!/usr/bin/env bash
# Bring the whole demo up in one command, and leave it ready to call.
#
#   backend/scripts/start_demo.sh
#
# Safe to run twice: anything already listening on the right port is reused rather than
# duplicated, and the reserved ngrok domain means the public URL never changes, so the
# ElevenLabs webhook and MCP registration stay valid across restarts.
#
# Prints no keys or tokens. Logs go to backend/.local-logs/ (gitignored).
set -uo pipefail

NGROK_DOMAIN="${NGROK_DOMAIN:-reprint-purveyor-foil.ngrok-free.dev}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="$(cd "$BACKEND_DIR/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/eride-repo"
LOGS="$BACKEND_DIR/.local-logs"
PYTHON="${PYTHON:-$BACKEND_DIR/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="$ROOT_DIR/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

mkdir -p "$LOGS"
step() { printf '\n==> %s\n' "$1"; }
listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

wait_for() {  # wait_for <url> <seconds> <label>
  local url="$1" limit="$2" label="$3" i=0
  while [ "$i" -lt "$limit" ]; do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      echo "    $label is up"
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  echo "    $label did not come up in ${limit}s. See $LOGS/"
  return 1
}

step "backend on port $BACKEND_PORT"
if listening "$BACKEND_PORT"; then
  echo "    already listening, reusing it"
else
  ( cd "$BACKEND_DIR" && nohup "$PYTHON" -m uvicorn app.main:app \
      --host 127.0.0.1 --port "$BACKEND_PORT" >"$LOGS/backend.log" 2>&1 & )
fi
wait_for "http://127.0.0.1:$BACKEND_PORT/health" 40 "backend" || exit 1

step "ngrok on $NGROK_DOMAIN"
if pgrep -f "ngrok http" >/dev/null 2>&1; then
  echo "    ngrok already running, reusing it"
else
  # --url pins the reserved domain, so PUBLIC_URL never has to change.
  nohup ngrok http "$BACKEND_PORT" --url "$NGROK_DOMAIN" >"$LOGS/ngrok.log" 2>&1 &
fi
wait_for "https://$NGROK_DOMAIN/health" 40 "tunnel" || exit 1

step "registering the voice agent"
# Re-asserts the MCP registration, the agent prompt and model, the workspace webhook and the
# phone number binding. It places no call and sends no text.
( cd "$BACKEND_DIR" && "$PYTHON" scripts/setup_voice.py ) || {
  echo "    setup_voice.py failed. The call will not connect until this passes."
  exit 1
}

step "resetting demo data and logins"
( cd "$BACKEND_DIR" && "$PYTHON" scripts/demo_state.py ) || exit 1

step "frontend on port $FRONTEND_PORT"
if listening "$FRONTEND_PORT"; then
  echo "    already listening, reusing it"
elif [ -d "$FRONTEND_DIR/node_modules" ]; then
  ( cd "$FRONTEND_DIR" && BACKEND_URL="http://127.0.0.1:$BACKEND_PORT" \
      nohup npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort \
      >"$LOGS/frontend.log" 2>&1 & )
else
  echo "    node_modules is missing. Run npm install in eride-repo first."
fi
wait_for "http://127.0.0.1:$FRONTEND_PORT/" 90 "frontend"

step "preflight"
( cd "$BACKEND_DIR" && "$PYTHON" scripts/preflight.py )
