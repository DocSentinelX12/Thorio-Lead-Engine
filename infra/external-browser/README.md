# Thorio external browser worker

This is the canonical persistent browser runtime for Thorio collection. It is
designed for an always-on external Linux VM, not a phone.

## Runtime

- Chromium runs headless as a systemd service.
- The authenticated browser profile persists on the VM at
  `/opt/thorio-lead-engine/browser-profile`.
- Playwright launches the supported Linux Chromium build.
- CDP is bound only to `127.0.0.1:9222`.
- The Lead Engine service starts only after the browser service is available.
- Both services restart automatically after failure or reboot.
- Authentication uses the existing Thorio browser account flow. A valid
  existing session is reused. Normal credential-based login is attempted only
  when the session is not valid. CAPTCHA, MFA, rate limits, and other platform
  security controls are never bypassed.

## Deployment target

Oracle Cloud's Always Free Ampere A1 VM is the preferred first target because
Oracle currently provides up to 2 OCPUs and 12 GB RAM for Always Free A1
compute, plus persistent block storage. Ubuntu ARM64 images are available.
The VM must remain within the Always Free allocation.

## Setup

Run `bootstrap.sh` as root on the persistent Linux VM. Keep the VM's private
`/etc/thorio/engine.env` file outside source control. Put the existing
authenticated browser target definitions and runtime credentials there using
the repository's existing environment-variable contract.

Do not expose port 9222 publicly. The browser worker and Lead Engine attach
locally on the same VM.
