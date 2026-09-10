# Thorio Android persistent browser node

This is the $0 persistent browser environment for the six authenticated Thorio collection accounts when no desktop or cloud VM is available.

## Why this exists

GitHub-hosted Actions runners are new VMs for workflow jobs, so their local browser profile is not a permanent machine. Playwright can use a persistent user-data directory, but that directory has to live somewhere persistent. This node keeps that directory on the user's Android device and exposes the local Chromium session to the Thorio engine over loopback CDP.

## Components

- `bootstrap.sh` installs the free Termux runtime, Chromium, the Thorio engine, and persistent runit services.
- `authorize-browser.sh` starts the dedicated Chromium profile for one-time interactive authorization.
- Chromium then runs continuously with the same profile on `127.0.0.1:9222`.
- Thorio attaches with `THORIO_BROWSER_CDP_URL=http://127.0.0.1:9222`.
- The engine runs locally with `run-scheduled --interval 60 --forever` and writes its normal durable state to the phone.
- Termux:Boot starts the browser and engine after device reboot.

## One-time setup

1. Install Termux from the official Termux project and install the official Termux:X11 companion app. Termux:X11 is required only for the one-time graphical authorization step.
2. Run `bootstrap.sh`.
3. Run `authorize-browser.sh`.
4. In the dedicated Thorio Chromium profile, log into LinkedIn, X, Threads, Facebook, Hacker News, and Indie Hackers normally. Complete any normal MFA or verification. Never bypass CAPTCHA, MFA, rate limits, or other security controls.
5. Return to Termux and let the script restart the persistent headless browser and engine.
6. Put Termux and Termux:X11 in Android battery usage `Unrestricted`, keep the phone charging for continuous operation, and install Termux:Boot so the node restarts after reboot.
7. Put the existing Airtable runtime settings and the six browser target definitions in the private `~/.thorio/engine.env` file. Do not put them in the repository.

The dedicated browser profile is separate from the user's normal Android Chrome profile.
