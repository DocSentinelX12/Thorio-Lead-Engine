#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${RUNNER_NAME:?RUNNER_NAME is required}"

RUNNER_ROOT="${RUNNER_ROOT:-/opt/actions-runner}"
RUNNER_LABELS="${RUNNER_LABELS:-gpu,cuda}"
RUNNER_VERSION="${RUNNER_VERSION:-}"
GITHUB_API_URL="${GITHUB_API_URL:-https://api.github.com}"
GITHUB_API_VERSION="${GITHUB_API_VERSION:-2026-03-10}"
RUNNER_GROUP_ID="${GITHUB_RUNNER_GROUP_ID:-1}"

# JIT is the preferred registration mechanism. The API token must have
# repository Administration: write permission. A legacy registration token is
# retained only as an explicit compatibility fallback.
JIT_TOKEN="${GITHUB_RUNNER_JIT_TOKEN:-}"
REGISTRATION_TOKEN="${GITHUB_RUNNER_REGISTRATION_TOKEN:-}"

if [ -z "${JIT_TOKEN}" ] && [ -z "${REGISTRATION_TOKEN}" ]; then
  echo "GPU RUNNER REFUSED: neither GITHUB_RUNNER_JIT_TOKEN nor GITHUB_RUNNER_REGISTRATION_TOKEN is configured." >&2
  exit 22
fi

mkdir -p "${RUNNER_ROOT}"
cd "${RUNNER_ROOT}"

# Never register a machine as a GPU runner until the physical NVIDIA device
# and CUDA runtime are observable locally.
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

if [ -z "${RUNNER_VERSION}" ] || [ -z "${RUNNER_DOWNLOAD_URL}" ]; then
  : "${GITHUB_RUNNER_JIT_TOKEN:?GITHUB_RUNNER_JIT_TOKEN is required to discover the repository runner application}"
  RUNNER_DOWNLOAD_JSON="$(
    curl --fail --silent --show-error --location       -H 'Accept: application/vnd.github+json'       -H "Authorization: Bearer ${GITHUB_RUNNER_JIT_TOKEN}"       -H "X-GitHub-Api-Version: ${GITHUB_API_VERSION}"       "${GITHUB_API_URL}/repos/${GITHUB_REPOSITORY}/actions/runners/downloads"
  )"
  RUNNER_DOWNLOAD_METADATA="$(
    python3 - "${RUNNER_DOWNLOAD_JSON}" "${ASSET_ARCH}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
wanted_arch = sys.argv[2]
for item in payload:
    if (
        isinstance(item, dict)
        and item.get("os") == "linux"
        and item.get("architecture") == wanted_arch
        and isinstance(item.get("download_url"), str)
        and isinstance(item.get("filename"), str)
    ):
        print(item["filename"])
        print(item["download_url"])
        break
else:
    raise SystemExit(
        f"GPU RUNNER REFUSED: GitHub returned no Linux {wanted_arch} runner application."
    )
PY
  )"
  RUNNER_TARBALL_NAME="$(printf '%s\n' "${RUNNER_DOWNLOAD_METADATA}" | sed -n '1p')"
  RUNNER_DOWNLOAD_URL="$(printf '%s\n' "${RUNNER_DOWNLOAD_METADATA}" | sed -n '2p')"
  RUNNER_VERSION="$(printf '%s' "${RUNNER_TARBALL_NAME}" | sed -E 's/^actions-runner-linux-[^-]+-([0-9.]+)\.tar\.gz$/\1/')"
  if [ -z "${RUNNER_VERSION}" ] || [ "${RUNNER_VERSION}" = "${RUNNER_TARBALL_NAME}" ]; then
    echo "GPU RUNNER REFUSED: could not determine runner version from ${RUNNER_TARBALL_NAME}." >&2
    exit 22
  fi
else
  RUNNER_TARBALL_NAME="actions-runner-linux-${ASSET_ARCH}-${RUNNER_VERSION}.tar.gz"
  RUNNER_DOWNLOAD_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${RUNNER_TARBALL_NAME}"
fi

TARBALL="${RUNNER_TARBALL_NAME}"
BASE_URL="${RUNNER_DOWNLOAD_URL%/${TARBALL}}"

if [ ! -x "${RUNNER_ROOT}/config.sh" ]; then
  curl --fail --silent --show-error --location     "${RUNNER_DOWNLOAD_URL}"     --output "${RUNNER_ROOT}/${TARBALL}"
  curl --fail --silent --show-error --location     "${BASE_URL}/${TARBALL}.sha256"     --output "${RUNNER_ROOT}/${TARBALL}.sha256"
  (
    cd "${RUNNER_ROOT}"
    sha256sum --check "${TARBALL}.sha256"
    tar xzf "${TARBALL}"
    rm -f "${TARBALL}" "${TARBALL}.sha256"
  )
fi

echo "GPU RUNNER PHASE: requesting GitHub JIT runner configuration." >&2
JIT_CONFIG=""
if [ -n "${JIT_TOKEN}" ]; then
  JIT_CONFIG="$(
    GITHUB_RUNNER_JIT_TOKEN="${JIT_TOKEN}" python3 - "${GITHUB_API_URL}" "${GITHUB_API_VERSION}" "${GITHUB_REPOSITORY}" "${RUNNER_GROUP_ID}" "${RUNNER_NAME}" "${RUNNER_LABELS}" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

api_url, api_version, repository, group_id, name, labels_csv = sys.argv[1:]
token = os.environ.get("GITHUB_RUNNER_JIT_TOKEN", "")
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

  # JIT runners are already ephemeral and are automatically removed after one
  # job. Do not call config.sh or attempt a second registration.
  printf '%s\n' "GPU RUNNER PHASE: launching Actions runner with JIT configuration." >&2
  exec ./run.sh --jitconfig "${JIT_CONFIG}"
fi

./config.sh   --unattended   --replace   --ephemeral   --url "https://github.com/${GITHUB_REPOSITORY}"   --token "${REGISTRATION_TOKEN}"   --name "${RUNNER_NAME}"   --labels "${RUNNER_LABELS}"   --work "_work"

trap './config.sh remove --unattended --token "${REGISTRATION_TOKEN}" >/dev/null 2>&1 || true' EXIT

exec ./run.sh
