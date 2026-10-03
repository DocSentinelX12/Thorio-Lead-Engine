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

if [ -z "${RUNNER_VERSION}" ]; then
  RUNNER_VERSION="$(
    curl --fail --silent --show-error       -H 'Accept: application/vnd.github+json'       "${GITHUB_API_URL}/repos/actions/runner/releases/latest" |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"].lstrip("v"))'
  )"
fi

ARCH="$(uname -m)"
case "${ARCH}" in
  x86_64) ASSET_ARCH="x64" ;;
  aarch64|arm64) ASSET_ARCH="arm64" ;;
  *) echo "GPU RUNNER REFUSED: unsupported architecture ${ARCH}." >&2; exit 21 ;;
esac

TARBALL="actions-runner-linux-${ASSET_ARCH}-${RUNNER_VERSION}.tar.gz"
BASE_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}"

if [ ! -x "${RUNNER_ROOT}/config.sh" ]; then
  curl --fail --silent --show-error --location     "${BASE_URL}/${TARBALL}"     --output "${RUNNER_ROOT}/${TARBALL}"
  curl --fail --silent --show-error --location     "${BASE_URL}/${TARBALL}.sha256"     --output "${RUNNER_ROOT}/${TARBALL}.sha256"
  (
    cd "${RUNNER_ROOT}"
    sha256sum --check "${TARBALL}.sha256"
    tar xzf "${TARBALL}"
    rm -f "${TARBALL}" "${TARBALL}.sha256"
  )
fi

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

print(encoded)
PY
  )"

  # JIT runners are already ephemeral and are automatically removed after one
  # job. Do not call config.sh or attempt a second registration.
  exec ./run.sh --jitconfig "${JIT_CONFIG}"
fi

./config.sh   --unattended   --replace   --ephemeral   --url "https://github.com/${GITHUB_REPOSITORY}"   --token "${REGISTRATION_TOKEN}"   --name "${RUNNER_NAME}"   --labels "${RUNNER_LABELS}"   --work "_work"

trap './config.sh remove --unattended --token "${REGISTRATION_TOKEN}" >/dev/null 2>&1 || true' EXIT

exec ./run.sh
