#!/usr/bin/env bash
set -euo pipefail

# Free-only production node bootstrap. This script never asks for or stores
# social-account credentials. Browser authentication is performed interactively
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

install -d -o "${RUN_USER}" -g "${RUN_USER}" "${APP_DIR}/data" "${APP_DIR}/browser-profile" /etc/thorio

if [[ ! -f /etc/thorio/engine.env ]]; then
  compute_token="$(runuser -u "${RUN_USER}" -- "${APP_DIR}/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  cat > /etc/thorio/engine.env <<EOF
# Runtime configuration. Add or change secrets manually on the machine.
# Never commit this file or paste credentials into chat.
LEAD_ENGINE_DATA_DIR=${APP_DIR}/data
THORIO_BROWSER_PROFILE_DIR=${APP_DIR}/browser-profile
THORIO_FREE_ONLY=1
THORIO_COMPUTE_AUTH_TOKEN=${compute_token}
THORIO_COMPUTE_DB=${APP_DIR}/data/coordinator.sqlite3
THORIO_COMPUTE_BIND_HOST=127.0.0.1
THORIO_COMPUTE_PORT=8787
THORIO_COMPUTE_COORDINATOR_URL=http://127.0.0.1:8787
THORIO_WORKER_ID=%H-local
EOF
  chmod 600 /etc/thorio/engine.env
  chown root:root /etc/thorio/engine.env
fi

cat > /etc/systemd/system/thorio-lead-engine.service <<EOF
[Unit]
Description=Thorio Lead Engine persistent free compute node
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=-/etc/thorio/engine.env
Environment=THORIO_FREE_ONLY=1
Environment=THORIO_NODE_ID=%H
Environment=THORIO_BROWSER_PROFILE_DIR=${APP_DIR}/browser-profile
Environment=LEAD_ENGINE_DATA_DIR=${APP_DIR}/data
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

cat > /etc/systemd/system/thorio-compute-coordinator.service <<EOF
[Unit]
Description=Thorio free compute coordinator
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=-/etc/thorio/engine.env
Environment=THORIO_FREE_ONLY=1
Environment=THORIO_COMPUTE_DB=${APP_DIR}/data/coordinator.sqlite3
ExecStart=${APP_DIR}/.venv/bin/python -m lead_engine.compute_coordinator
Restart=always
RestartSec=5
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${APP_DIR}/data

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/thorio-compute-worker.service <<EOF
[Unit]
Description=Thorio free local compute worker
After=thorio-compute-coordinator.service network-online.target
Requires=thorio-compute-coordinator.service
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=-/etc/thorio/engine.env
Environment=THORIO_FREE_ONLY=1
ExecStart=${APP_DIR}/.venv/bin/python -m lead_engine.compute_worker
Restart=always
RestartSec=5
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${APP_DIR}/data

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable thorio-lead-engine.service
systemctl enable thorio-compute-coordinator.service
systemctl enable thorio-compute-worker.service
systemctl restart thorio-compute-coordinator.service
systemctl restart thorio-compute-worker.service
systemctl restart thorio-lead-engine.service
systemctl --no-pager --full status thorio-compute-coordinator.service || true
systemctl --no-pager --full status thorio-compute-worker.service || true
systemctl --no-pager --full status thorio-lead-engine.service || true

echo "Free compute node bootstrap complete."
echo "Coordinator and local worker are persistent and restart automatically."
echo "For remote workers, configure a public HTTPS coordinator URL and TLS certificate/key in /etc/thorio/engine.env."
echo "Credentials were not requested or stored."
echo "Persistent browser authentication must be completed interactively on this node."
