#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_RUNNER_REGISTRATION_TOKEN:?GITHUB_RUNNER_REGISTRATION_TOKEN is required}"
: "${RUNNER_NAME:?RUNNER_NAME is required}"

RUNNER_ROOT="${RUNNER_ROOT:-/opt/actions-runner}"
RUNNER_LABELS="${RUNNER_LABELS:-gpu,cuda}"
RUNNER_VERSION="${RUNNER_VERSION:-}"

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
import subprocess
import sys

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
        raise SystemExit(f"GPU RUNNER REFUSED: CUDA execution checksum failed on device {index}.")
print(f"CUDA_VALIDATED_DEVICES={count}")
PY

if [ -z "${RUNNER_VERSION}" ]; then
  RUNNER_VERSION="$(
    curl --fail --silent --show-error       -H 'Accept: application/vnd.github+json'       https://api.github.com/repos/actions/runner/releases/latest |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"].lstrip("v"))'
  )"
fi

ARCH="$(uname -m)"
case "${ARCH}" in
  x86_64) ASSET_ARCH="x64" ;;
  aarch64|arm64) ASSET_ARCH="arm64" ;;
  *) echo "GPU RUNNER REFUSED: unsupported architecture ${ARCH}."; exit 21 ;;
esac

TARBALL="actions-runner-linux-${ASSET_ARCH}-${RUNNER_VERSION}.tar.gz"
BASE_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}"

if [ ! -x "${RUNNER_ROOT}/config.sh" ]; then
  curl --fail --silent --show-error --location "${BASE_URL}/${TARBALL}" --output "${RUNNER_ROOT}/${TARBALL}"
  curl --fail --silent --show-error --location "${BASE_URL}/${TARBALL}.sha256" --output "${RUNNER_ROOT}/${TARBALL}.sha256"
  (
    cd "${RUNNER_ROOT}"
    sha256sum --check "${TARBALL}.sha256"
    tar xzf "${TARBALL}"
    rm -f "${TARBALL}" "${TARBALL}.sha256"
  )
fi

./config.sh   --unattended   --replace   --ephemeral   --url "https://github.com/${GITHUB_REPOSITORY}"   --token "${GITHUB_RUNNER_REGISTRATION_TOKEN}"   --name "${RUNNER_NAME}"   --labels "${RUNNER_LABELS}"   --work "_work"

trap './config.sh remove --unattended --token "${GITHUB_RUNNER_REGISTRATION_TOKEN}" >/dev/null 2>&1 || true' EXIT

exec ./run.sh
