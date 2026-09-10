#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

source "$HOME/.thorio/engine.env"

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
PROFILE_DIR="${THORIO_BROWSER_PROFILE_DIR:-$HOME/.thorio/browser-profile}"
LOG_DIR="${HOME}/.thorio/logs"
CHROME="$PREFIX/lib/chromium/chrome"

mkdir -p "$LOG_DIR" "$PROFILE_DIR"

if ! command -v termux-x11 >/dev/null 2>&1; then
  echo "Termux:X11 runtime is not installed. The Android node must install the Termux:X11 package before authorization." >&2
  exit 1
fi

if [ ! -x "$CHROME" ]; then
  echo "Chromium executable not found at $CHROME." >&2
  exit 1
fi

sv down thorio-engine || true
sv down thorio-browser || true
pkill -f 'chromium.*remote-debugging-port=9222' || true

export DISPLAY=:1
unset XKB_CONFIG_ROOT

# Start the Android X11 server if it is not already running.
if ! pgrep -f '[t]ermux-x11 :1' >/dev/null 2>&1; then
  nohup termux-x11 :1 >"$LOG_DIR/thorio-x11.log" 2>&1 &
  sleep 3
fi

# Open the Termux:X11 Android activity.
am start --user 0 -n com.termux.x11/com.termux.x11.MainActivity >/dev/null 2>&1 || true
sleep 2

# Launch a visible Chromium instance using the dedicated Thorio profile.
# CDP remains bound to localhost so the engine can attach without exposing it to the network.
nohup "$CHROME" \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --no-first-run \
  --disable-background-networking \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir="$PROFILE_DIR" \
  about:blank >"$LOG_DIR/thorio-chromium-auth.log" 2>&1 &

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
  echo "Chromium started but CDP did not become reachable on 127.0.0.1:9222." >&2
  echo "See $LOG_DIR/thorio-chromium-auth.log for the local Chromium error." >&2
  exit 1
fi

cat <<'EOF'

THORIO ONE-TIME BROWSER AUTHORIZATION

Chromium is now running with the dedicated Thorio profile.
Log into these six accounts there normally:
  1. LinkedIn
  2. X
  3. Threads
  4. Facebook
  5. Hacker News
  6. Indie Hackers

Complete any normal MFA or verification requested by the sites.
Do not bypass CAPTCHA, MFA, rate limits, or other security controls.

When all six accounts are authorized, return to Termux and press Enter.
EOF

read -r -p "Press Enter after the six accounts are authorized... " _

# The persistent service owns the browser after authorization.
sv up thorio-browser
sv up thorio-engine

echo "Persistent Thorio browser and engine services restarted."
