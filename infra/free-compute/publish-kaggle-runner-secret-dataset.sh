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

# Kaggle datasets are private by default. Do not request public visibility or rely on
# an unsupported isPrivate field in dataset-metadata.json. The token is never
# placed in kernel source, metadata, command arguments, or logs.
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
            "licenses": [{"name": "other"}],
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
PY

kaggle datasets create -p "${workdir}"
# Kaggle's documented create behavior is private by default; this command deliberately
# leaves the default private visibility unchanged. Avoid the metadata-download endpoint here: it has returned 403
# or metadata documents without identity fields immediately after successful creation.
# Verify the exact owner/slug directly by listing files through that dataset reference.
printf 'THORIO_PRIVATE_RUNNER_CREDENTIAL_DATASET_READY ref=%s visibility=private-by-default\\n' "${dataset_ref}"

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
