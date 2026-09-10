#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

source "$HOME/.thorio/engine.env"

if ! command -v termux-x11 >/dev/null 2>&1; then
  echo "Termux:X11 is not installed. Install the official Termux:X11 companion app and the termux-x11-nightly package first." >&2
  exit 1
fi

sv down thorio-engine || true
sv down thorio-browser || true
pkill -f 'chromium.*remote-debugging-port=9222' || true

mkdir -p "$THORIO_BROWSER_PROFILE_DIR"
export DISPLAY=:1
export XKB_CONFIG_ROOT="$PREFIX/share/xcb"

termux-x11 :1 >/tmp/thorio-x11.log 2>&1 &
sleep 3
am start --user 0 -n com.termux.x11/com.termux.x11.MainActivity >/dev/null 2>&1 || true

cat <<'EOF'

THORIO ONE-TIME BROWSER AUTHORIZATION

A dedicated Chromium profile will open on the Android device.
Log into the six accounts there normally:
  1. LinkedIn
  2. X
  3. Threads
  4. Facebook
  5. Hacker News
  6. Indie Hackers

Complete any normal MFA or verification requested by the sites.
Do not bypass CAPTCHA, MFA, rate limits, or other security controls.

When all six accounts are authorized, return to Termux and press Enter.
The profile is stored locally and will be reused by the persistent node.
EOF

read -r -p "Press Enter after the six accounts are authorized... " _

pkill -f 'chromium.*remote-debugging-port=9222' || true
sv up thorio-browser
sv up thorio-engine

echo "Persistent browser service restarted."
