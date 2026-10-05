# Thorio external browser collection

The phone and Lightning runtime paths are removed. Browser collection runs on
GitHub-hosted Linux runners, which are external to the phone and are recreated
for each job.

GitHub-hosted standard runners are free for this public repository. Because
the runner filesystem is ephemeral, Thorio persists only the Playwright
authenticated storage state between production runs. That state contains
browser cookies and web storage, so it is encrypted before it is uploaded as
an Actions artifact.

## Runtime

- browser-worker.py starts headless Chromium and exposes CDP only on
  127.0.0.1:9222.
- browser-worker.py restores the encrypted Playwright storage state when one
  exists and saves the current state when the run ends.
- browser-state.py encrypts and decrypts that state with a dedicated
  GitHub Actions secret.
- .github/workflows/python-app.yml starts the browser before the production
  Lead Engine cycle and saves the encrypted state afterward.
- The existing authenticated account credentials remain GitHub Actions
  secrets. They are used only through the normal authorized login flow when an
  existing session is no longer valid.
- The phone is not part of runtime execution.
- No CAPTCHA, MFA, rate-limit, or platform security control is bypassed.

## Required GitHub configuration

Create the repository secret:

THORIO_BROWSER_STATE_ENCRYPTION_KEY

It must be a valid Fernet key. This is the only new secret required for
persistent browser-state storage.

If browser discovery targets are configured, provide them through:

THORIO_BROWSER_DISCOVERY_TARGETS

The production workflow already passes that secret through to the browser
collector without printing its value.

## Persistence and recovery

The encrypted browser-state artifact is retained for 90 days. Each successful
production run looks for the newest successful run containing that artifact,
decrypts it only on the ephemeral runner, and starts Chromium with the
recovered authentication state.

If no state artifact exists, the browser starts without persisted state and
the existing normal account authentication flow is allowed to establish a
new session. A platform security challenge can still require normal
verification. The system does not attempt to defeat such a challenge.

The plaintext browser state is never uploaded as an artifact and is removed
after encryption.
