# Thorio external browser worker

The phone path has been removed. Browser collection now runs on an external
Linux environment and keeps its authenticated profile on persistent storage.

## First no-card target: Lightning AI free Studio

Lightning currently advertises one free active Studio with no credit card,
persistent storage, SSH access, and background execution. Free Studios require
a restart every four hours. Lightning also documents that Studio files,
packages, and environment state persist across restarts.

That makes the free Studio a practical no-card target for this browser worker:
the Chromium process restarts, but the Thorio browser profile remains on the
persistent Studio filesystem. The existing authentication code reuses a valid
session and only attempts normal login when the session is invalid.

Lightning requires phone verification for account security. This is account
verification only. The phone is not the browser runtime.

## Files

- `browser-worker.py` launches one persistent headless Chromium profile and
  binds CDP only to localhost.
- `lightning-supervisor.py` keeps the browser and Lead Engine processes alive
  and restarts either process if it exits.
- `lightning-start.sh` is the on-start launcher for a Lightning Studio.
- `bootstrap.sh` is for a conventional persistent Linux VM with systemd.

## Authentication

No daily manual authorization is built into this runtime. The existing
`account_auth` and browser discovery flow remain responsible for normal
authenticated sessions. Credentials and target definitions must be supplied
through the existing private runtime environment or the provider's secret
facility. CAPTCHA, MFA, rate limits, and other platform security controls are
never bypassed.

CDP is never exposed publicly. Keep port 9222 local to the browser host.
