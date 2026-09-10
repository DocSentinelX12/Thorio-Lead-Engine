#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# Thorio Android/Termux persistent node.
# This keeps the authorized browser profile on the user's own Android device.
# It does not collect, transmit, or store social credentials in the repository.

APP_DIR="${THORIO_ANDROID_APP_DIR:-$HOME/thorio-lead-engine}"
PROFILE_DIR="${THORIO_ANDROID_BROWSER_PROFILE:-$HOME/.thorio/browser-profile}"
ENV_FILE="${THORIO_ANDROID_ENV_FILE:-$HOME/.thorio/engine.env}"

pkg update -y
pkg install -y git python termux-services curl x11-repo chromium

mkdir -p "$HOME/.thorio" "$PROFILE_DIR" "$APP_DIR"

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --prune origin main
  git -C "$APP_DIR" reset --hard origin/main
else
  rm -rf "$APP_DIR"
  git clone --branch main --single-branch https://github.com/DocSentinelX12/Thorio-Lead-Engine.git "$APP_DIR"
fi

python -m pip install --upgrade pip
python -m pip install -r "$APP_DIR/requirements.txt"
if [ -f "$APP_DIR/requirements-browser.txt" ]; then
  python -m pip install -r "$APP_DIR/requirements-browser.txt"
fi

cat > "$ENV_FILE" <<EOF
# Thorio Android node runtime configuration.
# Keep this file private on the phone. Never commit it.
export LEAD_ENGINE_DATA_DIR=$APP_DIR/data
export THORIO_FREE_ONLY=1
export THORIO_BROWSER_PROFILE_DIR=$PROFILE_DIR
export THORIO_BROWSER_CDP_URL=http://127.0.0.1:9222
export THORIO_BROWSER_HEADLESS=1
# Add the existing Airtable credentials here locally on the phone.
# export AIRTABLE_API_KEY=...
# export AIRTABLE_BASE_ID=appxz89RYpxIOpdMD
# Add the existing browser target JSON locally after defining the six feed targets.
# export THORIO_BROWSER_DISCOVERY_TARGETS='[...]'
EOF
chmod 600 "$ENV_FILE"

mkdir -p "$HOME/.termux/service/thorio-browser" "$HOME/.termux/service/thorio-engine"

cat > "$HOME/.termux/service/thorio-browser/run" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
source "$HOME/.thorio/engine.env"
mkdir -p "$THORIO_BROWSER_PROFILE_DIR"
exec chromium-browser \
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
chmod +x "$HOME/.termux/service/thorio-browser/run"

cat > "$HOME/.termux/service/thorio-engine/run" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
source "$HOME/.thorio/engine.env"
cd "$HOME/thorio-lead-engine"
exec python -m lead_engine.cli run-scheduled --interval 60 --forever
EOF
chmod +x "$HOME/.termux/service/thorio-engine/run"

# Termux:Boot will start these services after reboot when the companion app is installed.
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/thorio-start" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock || true
sv-enable thorio-browser || true
sv-enable thorio-engine || true
sv up thorio-browser || true
sv up thorio-engine || true
EOF
chmod +x "$HOME/.termux/boot/thorio-start"

sv-enable thorio-browser || true
sv-enable thorio-engine || true

echo "Thorio Android node installed."
echo "Next: complete one-time browser login in the dedicated Thorio Chromium profile, then keep the phone charging and set Termux battery usage to Unrestricted."
echo "Do not use your normal Chrome profile. The Thorio profile is $PROFILE_DIR."
