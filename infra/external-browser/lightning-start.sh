#!/usr/bin/env bash
set -euo pipefail

# Lightning AI free Studio launcher for the persistent Thorio browser worker.
# Put this command in the Studio's on-start script after the repository has
# been cloned and dependencies have been installed once.

ROOT="${THORIO_APP_DIR:-$HOME/thorio-lead-engine}"
ENV_FILE="${THORIO_EXTERNAL_BROWSER_ENV_FILE:-$HOME/.thorio/engine.env}"
LOG_DIR="${THORIO_EXTERNAL_BROWSER_LOG_DIR:-$HOME/.thorio/logs}"

mkdir -p "$HOME/.thorio" "$HOME/.thorio/browser-profile" "$LOG_DIR"

if [ ! -d "$ROOT/.git" ]; then
  git clone --branch main --single-branch https://github.com/DocSentinelX12/Thorio-Lead-Engine.git "$ROOT"
fi

if [ ! -f "$ROOT/.venv/bin/python" ]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/python" -m pip install --upgrade pip
  "$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
  "$ROOT/.venv/bin/pip" install -r "$ROOT/requirements-browser.txt"
  "$ROOT/.venv/bin/python" -m playwright install chromium --no-shell
fi

if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<EOF
LEAD_ENGINE_DATA_DIR=$ROOT/data
THORIO_BROWSER_PROFILE_DIR=$HOME/.thorio/browser-profile
THORIO_BROWSER_CDP_URL=http://127.0.0.1:9222
THORIO_BROWSER_CDP_PORT=9222
THORIO_BROWSER_HEADLESS=1
THORIO_FREE_ONLY=1
EOF
  chmod 600 "$ENV_FILE"
fi

if ! pgrep -f "infra/external-browser/lightning-supervisor.py" >/dev/null 2>&1; then
  nohup "$ROOT/.venv/bin/python" "$ROOT/infra/external-browser/lightning-supervisor.py"     >>"$LOG_DIR/thorio-supervisor.log" 2>&1 &
fi

echo "Thorio external browser supervisor is running."
echo "Persistent profile: $HOME/.thorio/browser-profile"
echo "CDP: http://127.0.0.1:9222 (localhost only)"
