#!/usr/bin/env bash
set -euo pipefail

: "${KAGGLE_USERNAME:?KAGGLE_USERNAME is required}"
: "${KAGGLE_API_TOKEN:?KAGGLE_API_TOKEN is required}"
: "${GITHUB_RUNNER_JIT_TOKEN:?GITHUB_RUNNER_JIT_TOKEN is required}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
: "${GITHUB_RUN_ATTEMPT:?GITHUB_RUN_ATTEMPT is required}"
: "${THORIO_KAGGLE_SECRET_DATASET_SLUG:?THORIO_KAGGLE_SECRET_DATASET_SLUG is required}"

expected_slug="thorio-runner-credentials-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
if [[ "${THORIO_KAGGLE_SECRET_DATASET_SLUG}" != "${expected_slug}" ]]; then
  echo "Refusing unexpected runner credential dataset slug." >&2
  exit 1
fi

dataset_slug="${THORIO_KAGGLE_SECRET_DATASET_SLUG}"
dataset_ref="${KAGGLE_USERNAME}/${dataset_slug}"
workdir="$(mktemp -d)"
verify_dir="$(mktemp -d)"
cleanup_temp() {
  rm -rf "${workdir}" "${verify_dir}"
}
trap cleanup_temp EXIT

# The token is written only to a temporary file that is uploaded as a private
# dataset. It is never placed in kernel source, metadata, command arguments, or logs.
printf '%s' "${GITHUB_RUNNER_JIT_TOKEN}" > "${workdir}/runner-token"
chmod 600 "${workdir}/runner-token"
python - "${workdir}/dataset-metadata.json" "${dataset_ref}" "${dataset_slug}" <<'PY'
import json
import sys
from pathlib import Path

metadata_path, dataset_ref, dataset_slug = sys.argv[1:]
Path(metadata_path).write_text(
    json.dumps(
        {
            "id": dataset_ref,
            "title": dataset_slug,
            "isPrivate": True,
            "licenses": [{"name": "other"}],
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
PY

kaggle datasets create -p "${workdir}"
kaggle datasets metadata "${dataset_ref}" -p "${verify_dir}"
python - "${verify_dir}/dataset-metadata.json" "${dataset_ref}" <<'PY'
import json
import sys
from pathlib import Path

metadata_path, dataset_ref = sys.argv[1:]
path = Path(metadata_path)
if not path.is_file():
    raise SystemExit("Kaggle did not return dataset metadata for private-visibility verification.")
metadata = json.loads(path.read_text(encoding="utf-8"))
if str(metadata.get("id") or "").strip() != dataset_ref:
    raise SystemExit("Kaggle returned metadata for a different runner credential dataset.")
if metadata.get("isPrivate") is not True:
    raise SystemExit("Runner credential dataset is not verified private; refusing GPU acquisition.")
print(f"THORIO_PRIVATE_RUNNER_CREDENTIAL_DATASET_READY ref={dataset_ref} private=true", flush=True)
PY

kaggle datasets files "${dataset_ref}" --csv > "${verify_dir}/dataset-files.csv"
python - "${verify_dir}/dataset-files.csv" <<'PY'
import csv
import sys
from pathlib import Path

with open(sys.argv[1], newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))
if not any(
    Path(str(value or "")).name == "runner-token"
    for row in rows
    for value in row.values()
):
    raise SystemExit("Private runner credential dataset does not contain runner-token; refusing GPU acquisition.")
print("THORIO_PRIVATE_RUNNER_CREDENTIAL_FILE_VERIFIED", flush=True)
PY
