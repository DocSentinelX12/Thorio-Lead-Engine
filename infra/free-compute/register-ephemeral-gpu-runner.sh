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

# Resolve the exact published runner asset through GitHub's release API.
# Store the API response on disk so no large JSON payload enters argv.
# Download through the release-asset API rather than the browser redirect URL.
if [ -n "${RUNNER_DOWNLOAD_URL:-}" ] && [ -n "${RUNNER_TARBALL_NAME:-}" ]; then
  : "using explicitly supplied runner asset"
elif [ -n "${RUNNER_VERSION:-}" ]; then
  RELEASE_JSON_FILE="$(mktemp)"
  trap 'rm -f "${RELEASE_JSON_FILE}"' EXIT
  curl --fail --silent --show-error --location \
    -H 'Accept: application/vnd.github+json' \
    -H "X-GitHub-Api-Version: ${GITHUB_API_VERSION}" \
    "${GITHUB_API_URL}/repos/actions/runner/releases/tags/v${RUNNER_VERSION}" \
    --output "${RELEASE_JSON_FILE}"
  RUNNER_ASSET_METADATA="$(python3 - "${RELEASE_JSON_FILE}" "${ASSET_ARCH}" <<'PY'
import json
import sys

path, wanted_arch = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    release = json.load(handle)

for asset in release.get("assets", []):
    if not isinstance(asset, dict):
        continue
    filename = asset.get("name")
    if filename != f"actions-runner-linux-{wanted_arch}-{release.get('tag_name', '').lstrip('v')}.tar.gz":
        continue
    asset_id = asset.get("id")
    digest = asset.get("digest")
    if not isinstance(asset_id, int):
        raise SystemExit("GPU RUNNER REFUSED: runner release asset has no numeric asset id.")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise SystemExit(f"GPU RUNNER REFUSED: runner release asset {filename} has no SHA-256 digest.")
    print(release["tag_name"].lstrip("v"))
    print(filename)
    print(asset_id)
    print(digest.removeprefix("sha256:"))
    raise SystemExit(0)

raise SystemExit(f"GPU RUNNER REFUSED: no Linux {wanted_arch} runner asset found in release.")
PY
  )"
  RUNNER_VERSION="$(printf '%s\n' "${RUNNER_ASSET_METADATA}" | sed -n '1p')"
  RUNNER_TARBALL_NAME="$(printf '%s\n' "${RUNNER_ASSET_METADATA}" | sed -n '2p')"
  RUNNER_ASSET_ID="$(printf '%s\n' "${RUNNER_ASSET_METADATA}" | sed -n '3p')"
  RUNNER_SHA256="$(printf '%s\n' "${RUNNER_ASSET_METADATA}" | sed -n '4p')"
  RUNNER_DOWNLOAD_URL="${GITHUB_API_URL}/repos/actions/runner/releases/assets/${RUNNER_ASSET_ID}"
else
  echo "GPU RUNNER REFUSED: runner asset or version is not configured." >&2
  exit 22
fi

TARBALL="${RUNNER_TARBALL_NAME}"

if [ ! -x "${RUNNER_ROOT}/config.sh" ]; then
  if [[ "${RUNNER_DOWNLOAD_URL}" == */releases/assets/* ]]; then
    curl --fail --silent --show-error --location \
      -H 'Accept: application/octet-stream' \
      -H "X-GitHub-Api-Version: ${GITHUB_API_VERSION}" \
      "${RUNNER_DOWNLOAD_URL}" \
      --output "${RUNNER_ROOT}/${TARBALL}"
  else
    curl --fail --silent --show-error --location "${RUNNER_DOWNLOAD_URL}" \
      --output "${RUNNER_ROOT}/${TARBALL}"
  fi

  if [ -n "${RUNNER_SHA256:-}" ]; then
    printf '%s  %s\n' "${RUNNER_SHA256}" "${TARBALL}" > "${RUNNER_ROOT}/${TARBALL}.sha256"
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
