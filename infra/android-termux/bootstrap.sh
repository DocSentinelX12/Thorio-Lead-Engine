#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

APP_DIR="${THORIO_ANDROID_APP_DIR:-$HOME/thorio-lead-engine}"
PROFILE_DIR="${THORIO_ANDROID_BROWSER_PROFILE:-$HOME/.thorio/browser-profile}"
ENV_FILE="${THORIO_ANDROID_ENV_FILE:-$HOME/.thorio/engine.env}"
SERVICE_DIR="${PREFIX:-/data/data/com.termux/files/usr}/var/service"
LOG_DIR="${PREFIX:-/data/data/com.termux/files/usr}/var/log"

pkg update -y
pkg install -y git python termux-services curl x11-repo chromium termux-x11-nightly

mkdir -p "$HOME/.thorio" "$PROFILE_DIR" "$APP_DIR"

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --prune origin main
  git -C "$APP_DIR" reset --hard origin/main
else
  rm -rf "$APP_DIR"
  git clone --branch main --single-branch https://github.com/DocSentinelX12/Thorio-Lead-Engine.git "$APP_DIR"
fi

python -m pip install -r "$APP_DIR/requirements.txt"
python -m pip install -r "$APP_DIR/requirements-browser.txt"

# Never overwrite an operator's private runtime configuration during an update.
# Credentials, browser targets, and other local state must survive bootstrap runs.
if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<EOF
# Private Android runtime configuration. Never commit this file.
export LEAD_ENGINE_DATA_DIR=$APP_DIR/data
export THORIO_FREE_ONLY=1
export THORIO_BROWSER_PROFILE_DIR=$PROFILE_DIR
export THORIO_BROWSER_CDP_URL=http://127.0.0.1:9222
export THORIO_BROWSER_HEADLESS=1
# Add existing Airtable runtime credentials locally if this node is intended to sync Airtable.
# export AIRTABLE_API_KEY=...
# export AIRTABLE_BASE_ID=appxz89RYpxIOpdMD
# Add the six browser feed target definitions locally after they are defined.
# export THORIO_BROWSER_DISCOVERY_TARGETS='[...]'
EOF
  chmod 600 "$ENV_FILE"
fi

mkdir -p "$SERVICE_DIR" "$LOG_DIR/sv"

cat > "$HOME/.thorio/start-services" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
SVDIR="$PREFIX/var/service"
LOGDIR="$PREFIX/var/log"
export SVDIR LOGDIR
mkdir -p "$SVDIR" "$LOGDIR/sv"
if ! pgrep -f "[r]unsvdir $SVDIR" >/dev/null 2>&1; then
  nohup "$PREFIX/bin/runsvdir" "$SVDIR" >/dev/null 2>&1 &
fi
for _ in $(seq 1 30); do
  [ -d "$SVDIR/thorio-browser/supervise" ] && [ -d "$SVDIR/thorio-engine/supervise" ] && break
  sleep 0.2
done
sv-enable thorio-browser
sv-enable thorio-engine
sv up thorio-browser
sv up thorio-engine
EOF
chmod +x "$HOME/.thorio/start-services"

mkdir -p "$SERVICE_DIR/thorio-browser/log" "$SERVICE_DIR/thorio-engine/log"

cat > "$SERVICE_DIR/thorio-browser/run" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
source "$HOME/.thorio/engine.env"
mkdir -p "$THORIO_BROWSER_PROFILE_DIR"
exec /data/data/com.termux/files/usr/lib/chromium/chrome \
  --headless \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --no-first-run \
  --disable-background-networking \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir="$THORIO_BROWSER_PROFILE_DIR" \
  about:blank
EOF
chmod +x "$SERVICE_DIR/thorio-browser/run"

cat > "$SERVICE_DIR/thorio-browser/log/run" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
exec svlogd -tt "$PREFIX/var/log/sv/thorio-browser"
EOF
chmod +x "$SERVICE_DIR/thorio-browser/log/run"

cat > "$SERVICE_DIR/thorio-engine/run" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
source "\$HOME/.thorio/engine.env"
cd "$APP_DIR"
exec python -m lead_engine.cli run-scheduled --interval 60 --forever
EOF
chmod +x "$SERVICE_DIR/thorio-engine/run"

cat > "$SERVICE_DIR/thorio-engine/log/run" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
exec svlogd -tt "$PREFIX/var/log/sv/thorio-engine"
EOF
chmod +x "$SERVICE_DIR/thorio-engine/log/run"

mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/thorio-start" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock || true
"$HOME/.thorio/start-services"
EOF
chmod +x "$HOME/.termux/boot/thorio-start"

"$HOME/.thorio/start-services"

echo "Thorio Android node installed and runit services started."
echo "Next: run infra/android-termux/authorize-browser.sh for one-time browser authorization."
echo "Dedicated profile: $PROFILE_DIR"
