#!/usr/bin/env bash
set -euo pipefail

# Persistent external browser node bootstrap.
# This node is headless and autonomous. It does not require a phone, Android,
# Termux, Termux:X11, or an interactive browser authorization session.

REPO_URL="${THORIO_REPO_URL:-https://github.com/DocSentinelX12/Thorio-Lead-Engine.git}"
APP_DIR="${THORIO_APP_DIR:-/opt/thorio-lead-engine}"
RUN_USER="${THORIO_RUN_USER:-${SUDO_USER:-$(id -un)}}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this bootstrap with sudo or as root." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git python3 python3-venv python3-pip ca-certificates curl

if ! id "${RUN_USER}" >/dev/null 2>&1; then
  echo "Configured run user does not exist: ${RUN_USER}" >&2
  exit 1
fi

install -d -o "${RUN_USER}" -g "${RUN_USER}" "${APP_DIR}"
if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" fetch --prune origin main
  git -C "${APP_DIR}" reset --hard origin/main
else
  rm -rf "${APP_DIR}"
  git clone --branch main --single-branch "${REPO_URL}" "${APP_DIR}"
  chown -R "${RUN_USER}:${RUN_USER}" "${APP_DIR}"
fi

runuser -u "${RUN_USER}" -- python3 -m venv "${APP_DIR}/.venv"
runuser -u "${RUN_USER}" -- "${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
runuser -u "${RUN_USER}" -- "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
runuser -u "${RUN_USER}" -- "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements-browser.txt"

# Use Playwright's supported Linux Chromium build instead of a distribution
# package whose browser lifecycle varies by Linux distribution and CPU.
${APP_DIR}/.venv/bin/python -m playwright install-deps chromium
runuser -u "${RUN_USER}" -- "${APP_DIR}/.venv/bin/python" -m playwright install chromium --no-shell

install -d -o "${RUN_USER}" -g "${RUN_USER}" "${APP_DIR}/data" "${APP_DIR}/browser-profile" /etc/thorio

if [[ ! -f /etc/thorio/engine.env ]]; then
  cat > /etc/thorio/engine.env <<EOF
# Private runtime configuration. Never commit this file.
LEAD_ENGINE_DATA_DIR=${APP_DIR}/data
THORIO_BROWSER_PROFILE_DIR=${APP_DIR}/browser-profile
THORIO_BROWSER_CDP_URL=http://127.0.0.1:9222
THORIO_BROWSER_CDP_PORT=9222
THORIO_BROWSER_HEADLESS=1
THORIO_FREE_ONLY=1
EOF
  chmod 600 /etc/thorio/engine.env
  chown root:root /etc/thorio/engine.env
fi

cat > /etc/systemd/system/thorio-browser.service <<EOF
[Unit]
Description=Thorio persistent external headless browser
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=-/etc/thorio/engine.env
Environment=THORIO_BROWSER_HEADLESS=1
Environment=THORIO_BROWSER_CDP_URL=http://127.0.0.1:9222
Environment=THORIO_BROWSER_CDP_PORT=9222
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/infra/external-browser/browser-worker.py
Restart=always
RestartSec=10
TimeoutStopSec=30
ExecStartPost=/bin/bash -c 'for i in $(seq 1 30); do curl -fsS http://127.0.0.1:9222/json/version >/dev/null 2>&1 && exit 0; sleep 1; done; echo "Thorio browser CDP did not become ready" >&2; exit 1'
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${APP_DIR}/data ${APP_DIR}/browser-profile

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/thorio-lead-engine.service <<EOF
[Unit]
Description=Thorio Lead Engine persistent external collection node
After=network-online.target thorio-browser.service
Wants=network-online.target
Requires=thorio-browser.service

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=-/etc/thorio/engine.env
Environment=THORIO_FREE_ONLY=1
ExecStart=${APP_DIR}/.venv/bin/python -m lead_engine.cli run-scheduled --interval 60 --forever
Restart=always
RestartSec=10
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${APP_DIR}/data ${APP_DIR}/browser-profile

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable thorio-browser.service
systemctl enable thorio-lead-engine.service
systemctl restart thorio-browser.service
systemctl restart thorio-lead-engine.service
systemctl --no-pager --full status thorio-browser.service || true
systemctl --no-pager --full status thorio-lead-engine.service || true

echo "Persistent external browser node bootstrap complete."
echo "Browser CDP is bound only to 127.0.0.1:9222."
echo "Browser profile: ${APP_DIR}/browser-profile"
echo "Runtime secrets and authenticated account settings remain in /etc/thorio/engine.env."
