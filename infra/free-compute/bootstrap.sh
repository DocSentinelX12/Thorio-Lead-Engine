#!/usr/bin/env bash
set -euo pipefail

# Free-only production node bootstrap. This script never asks for or stores
# credentials. Authentication for browser sources is performed interactively
# by the owner on the persistent machine.

REPO_URL="${THORIO_REPO_URL:-https://github.com/DocSentinelX12/Thorio-Lead-Engine.git}"
APP_DIR="${THORIO_APP_DIR:-/opt/thorio-lead-engine}"
RUN_USER="${THORIO_RUN_USER:-${SUDO_USER:-$(id -un)}}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this bootstrap with sudo or as root." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git python3 python3-venv python3-pip

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
if [[ -f "${APP_DIR}/requirements.txt" ]]; then
  runuser -u "${RUN_USER}" -- "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
fi
if [[ -f "${APP_DIR}/requirements-browser.txt" ]]; then
  runuser -u "${RUN_USER}" -- "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements-browser.txt"
fi

install -d -o "${RUN_USER}" -g "${RUN_USER}" "${APP_DIR}/data" "${APP_DIR}/browser-profile"

cat > /etc/systemd/system/thorio-lead-engine.service <<EOF
[Unit]
Description=Thorio Lead Engine persistent free compute node
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
Environment=THORIO_FREE_ONLY=1
Environment=THORIO_NODE_ID=%H
Environment=THORIO_BROWSER_PROFILE_DIR=${APP_DIR}/browser-profile
Environment=THORIO_DATA_DIR=${APP_DIR}/data
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
systemctl enable thorio-lead-engine.service
systemctl restart thorio-lead-engine.service
systemctl --no-pager --full status thorio-lead-engine.service || true

echo "Free compute node bootstrap complete."
echo "Credentials were not requested or stored."
echo "Persistent browser authentication must be completed interactively on this node."
