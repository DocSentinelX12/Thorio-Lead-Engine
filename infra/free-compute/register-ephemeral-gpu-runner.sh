#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${RUNNER_NAME:?RUNNER_NAME is required}"

RUNNER_ROOT="${RUNNER_ROOT:-/opt/actions-runner}"
RUNNER_LABELS="${RUNNER_LABELS:-gpu,cuda}"
RUNNER_VERSION="${RUNNER_VERSION:-2.337.0}"
GITHUB_API_URL="${GITHUB_API_URL:-https://api.github.com}"
GITHUB_API_VERSION="${GITHUB_API_VERSION:-2026-03-10}"
RUNNER_GROUP_ID="${GITHUB_RUNNER_GROUP_ID:-1}"

JIT_TOKEN_FILE="${GITHUB_RUNNER_JIT_TOKEN_FILE:-}"
REGISTRATION_TOKEN="${GITHUB_RUNNER_REGISTRATION_TOKEN:-}"

if [ -z "${JIT_TOKEN_FILE}" ] && [ -z "${GITHUB_RUNNER_JIT_TOKEN:-}" ] && [ -z "${REGISTRATION_TOKEN}" ]; then
  echo "GPU RUNNER REFUSED: neither GITHUB_RUNNER_JIT_TOKEN nor GITHUB_RUNNER_REGISTRATION_TOKEN is configured." >&2
  exit 22
fi

mkdir -p "${RUNNER_ROOT}"
cd "${RUNNER_ROOT}"

command -v nvidia-smi >/dev/null 2>&1 || {
  echo "GPU RUNNER REFUSED: nvidia-smi is unavailable."
  exit 20
}
nvidia-smi --query-gpu=uuid,name,driver_version --format=csv,noheader

python3 - <<'PY'
import importlib.util

if importlib.util.find_spec("torch") is None:
    raise SystemExit("GPU RUNNER REFUSED: PyTorch is not installed.")

import torch

if not torch.cuda.is_available():
    raise SystemExit("GPU RUNNER REFUSED: PyTorch cannot see CUDA.")

count = torch.cuda.device_count()
if count < 1:
    raise SystemExit("GPU RUNNER REFUSED: no CUDA devices are visible.")

for index in range(count):
    print(f"CUDA_DEVICE {index}: {torch.cuda.get_device_name(index)}")
    x = torch.tensor([2.0, 3.0], device=f"cuda:{index}")
    y = x * x
    if float(y.sum().item()) != 13.0:
        raise SystemExit(
            f"GPU RUNNER REFUSED: CUDA execution checksum failed on device {index}."
        )

print(f"CUDA_VALIDATED_DEVICES={count}")
PY

ARCH="$(uname -m)"
case "${ARCH}" in
  x86_64) ASSET_ARCH="x64" ;;
  aarch64|arm64) ASSET_ARCH="arm64" ;;
  *) echo "GPU RUNNER REFUSED: unsupported architecture ${ARCH}." >&2; exit 21 ;;
esac

# Prefer an explicitly supplied download URL. Otherwise, when a runner
# version is known, construct the public release asset URL directly. Only fall
# back to release discovery when neither value is available. This avoids
# passing a large releases JSON document through argv on constrained workers.
if [ -n "${RUNNER_DOWNLOAD_URL:-}" ]; then
  if [ -z "${RUNNER_TARBALL_NAME:-}" ]; then
    RUNNER_TARBALL_NAME="$(basename "${RUNNER_DOWNLOAD_URL}")"
  fi
elif [ -n "${RUNNER_VERSION:-}" ]; then
  RUNNER_TARBALL_NAME="actions-runner-linux-${ASSET_ARCH}-${RUNNER_VERSION}.tar.gz"
  RUNNER_DOWNLOAD_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${RUNNER_TARBALL_NAME}"
else
  RUNNER_RELEASE_JSON="$(
    curl --fail --silent --show-error --location \
      -H 'Accept: application/vnd.github+json' \
      -H "X-GitHub-Api-Version: ${GITHUB_API_VERSION}" \
      "${GITHUB_API_URL}/repos/actions/runner/releases?per_page=10"
  )"
  RUNNER_DOWNLOAD_METADATA="$(
    printf '%s' "${RUNNER_RELEASE_JSON}" | python3 - "${ASSET_ARCH}" <<'PY'
import json
import sys

payload = json.load(sys.stdin)
wanted_arch = sys.argv[1]

for release in payload:
    if (
        not isinstance(release, dict)
        or release.get("draft")
        or release.get("prerelease")
    ):
        continue
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v"):
        continue
    for asset in release.get("assets", []):
        if not isinstance(asset, dict):
            continue
        filename = asset.get("name")
        download_url = asset.get("browser_download_url")
        if (
            isinstance(filename, str)
            and filename == f"actions-runner-linux-{wanted_arch}-{tag[1:]}.tar.gz"
            and isinstance(download_url, str)
        ):
            digest = asset.get("digest")
            if not isinstance(digest, str) or not digest.startswith("sha256:"):
                raise SystemExit(
                    f"GPU RUNNER REFUSED: GitHub release asset {filename} has no SHA-256 digest."
                )
            print(tag[1:])
            print(filename)
            print(download_url)
            print(digest.removeprefix("sha256:"))
            raise SystemExit(0)

raise SystemExit(
    f"GPU RUNNER REFUSED: no published Linux {wanted_arch} actions/runner asset was found."
)
PY
  )"
  RUNNER_VERSION="$(printf '%s\n' "${RUNNER_DOWNLOAD_METADATA}" | sed -n '1p')"
  RUNNER_TARBALL_NAME="$(printf '%s\n' "${RUNNER_DOWNLOAD_METADATA}" | sed -n '2p')"
  RUNNER_DOWNLOAD_URL="$(printf '%s\n' "${RUNNER_DOWNLOAD_METADATA}" | sed -n '3p')"
  RUNNER_SHA256="$(printf '%s\n' "${RUNNER_DOWNLOAD_METADATA}" | sed -n '4p')"
fi

TARBALL="${RUNNER_TARBALL_NAME}"

if [ ! -x "${RUNNER_ROOT}/config.sh" ]; then
  curl --fail --silent --show-error --location "${RUNNER_DOWNLOAD_URL}" \
    --output "${RUNNER_ROOT}/${TARBALL}"

  if [ -n "${RUNNER_SHA256:-}" ]; then
    printf '%s  %s\\n' "${RUNNER_SHA256}" "${TARBALL}" > "${RUNNER_ROOT}/${TARBALL}.sha256"
  else
    BASE_URL="${RUNNER_DOWNLOAD_URL%/${TARBALL}}"
    curl --fail --silent --show-error --location "${BASE_URL}/${TARBALL}.sha256" \
      --output "${RUNNER_ROOT}/${TARBALL}.sha256"
  fi

  (
    cd "${RUNNER_ROOT}"
    sha256sum --check "${TARBALL}.sha256"
    tar xzf "${TARBALL}"
    rm -f "${TARBALL}" "${TARBALL}.sha256"
  )
fi

echo "GPU RUNNER PHASE: requesting GitHub JIT runner configuration." >&2
JIT_CONFIG=""
if [ -n "${JIT_TOKEN_FILE}" ] || [ -n "${GITHUB_RUNNER_JIT_TOKEN:-}" ]; then
  JIT_CONFIG="$(
    GITHUB_RUNNER_JIT_TOKEN_FILE="${JIT_TOKEN_FILE}" python3 - "${GITHUB_API_URL}" "${GITHUB_API_VERSION}" "${GITHUB_REPOSITORY}" "${RUNNER_GROUP_ID}" "${RUNNER_NAME}" "${RUNNER_LABELS}" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

api_url, api_version, repository, group_id, name, labels_csv = sys.argv[1:]
token_path = os.environ.get("GITHUB_RUNNER_JIT_TOKEN_FILE", "").strip()
if token_path:
    try:
        with open(token_path, encoding="utf-8") as handle:
            token = handle.read().strip()
    except OSError as exc:
        raise SystemExit(f"GPU RUNNER REFUSED: unable to read JIT token file: {exc}") from exc
else:
    token = os.environ.get("GITHUB_RUNNER_JIT_TOKEN", "").strip()
if not token:
    raise SystemExit("GPU RUNNER REFUSED: GitHub JIT token is empty.")
owner, repo = repository.split("/", 1)
payload = {
    "name": name,
    "runner_group_id": int(group_id),
    "labels": [item.strip() for item in labels_csv.split(",") if item.strip()],
    "work_folder": "_work",
}
request = urllib.request.Request(
    f"{api_url}/repos/{owner}/{repo}/actions/runners/generate-jitconfig",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": api_version,
        "Content-Type": "application/json",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
        if response.status != 201:
            raise RuntimeError(f"JIT configuration returned HTTP {response.status}")
except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
    raise SystemExit(f"GPU RUNNER REFUSED: JIT runner configuration failed: {exc}") from exc

encoded = body.get("encoded_jit_config")
if not isinstance(encoded, str) or not encoded:
    raise SystemExit("GPU RUNNER REFUSED: GitHub returned no encoded_jit_config.")

runner = body.get("runner")
if not isinstance(runner, dict):
    raise SystemExit("GPU RUNNER REFUSED: GitHub returned no runner metadata.")

runner_id = runner.get("id")
runner_name = runner.get("name")
runner_status = runner.get("status")
runner_labels = runner.get("labels")
if not isinstance(runner_id, int) or not runner_name or not runner_status:
    raise SystemExit("GPU RUNNER REFUSED: GitHub returned incomplete runner metadata.")
if not isinstance(runner_labels, list):
    raise SystemExit("GPU RUNNER REFUSED: GitHub returned invalid runner labels.")

metadata = {
    "id": runner_id,
    "name": runner_name,
    "status": runner_status,
    "labels": [
        label.get("name")
        for label in runner_labels
        if isinstance(label, dict) and isinstance(label.get("name"), str)
    ],
}
print(
    "GPU RUNNER JIT CREATED: "
    + json.dumps(metadata, sort_keys=True, separators=(",", ":")),
    file=sys.stderr,
    flush=True,
)
print(encoded)
PY
  )"
  printf '%s\n' "GPU RUNNER PHASE: GitHub JIT configuration received; starting ephemeral runner." >&2
  printf '%s\n' "GPU RUNNER PHASE: launching Actions runner with JIT configuration." >&2
  exec ./run.sh --jitconfig "${JIT_CONFIG}"
fi

./config.sh \
  --unattended \
  --replace \
  --ephemeral \
  --url "https://github.com/${GITHUB_REPOSITORY}" \
  --token "${REGISTRATION_TOKEN}" \
  --name "${RUNNER_NAME}" \
  --labels "${RUNNER_LABELS}" \
  --work "_work"

trap './config.sh remove --unattended --token "${REGISTRATION_TOKEN}" >/dev/null 2>&1 || true' EXIT

exec ./run.sh
