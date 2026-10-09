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

create_output="$(kaggle datasets create -p "${workdir}" 2>&1)"
printf '%s\n' "${create_output}"
# Require Kaggle's own upload confirmation for the exact secret filename.
# This proves the CLI reported uploading runner-token, without relying on the
# file-list endpoint that returned HTTP 403 in the observed runs.
if ! printf '%s\n' "${create_output}" | grep -Eq 'Upload successful:[[:space:]]*runner-token[[:space:]]+\([^)]*\)'; then
  echo "Kaggle did not confirm uploading runner-token; refusing GPU acquisition." >&2
  exit 1
fi
printf '%s\n' "THORIO_PRIVATE_RUNNER_CREDENTIAL_FILE_VERIFIED"

# Confirm the exact run-scoped dataset appears in the authenticated owner's
# dataset inventory. Parse CSV, require a valid ref header, and fail closed on
# malformed inventory or CLI errors. Do not use datasets files/metadata here:
# both endpoints have returned 403 or incomplete metadata after creation.
python - "${dataset_ref}" <<'PY'
import csv
import io
import subprocess
import sys
import time

target = sys.argv[1].strip().lower()
page = 1
deadline = time.monotonic() + 60
last_output = ""
while True:
    command = [
        "kaggle", "datasets", "list", "--mine",
        "--page", str(page), "--page-size", "100", "--csv",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-2000:]
        raise SystemExit(
            "Cannot verify the private runner credential dataset in owner inventory: "
            + detail
        )
    output = result.stdout or ""
    lines = [line for line in output.splitlines() if line.strip()]
    header_index = next(
        (index for index, line in enumerate(lines) if line.strip().lower().startswith("ref,")),
        None,
    )
    if header_index is None:
        # Kaggle acknowledges dataset creation before the owner inventory is
        # necessarily updated. Treat its explicit empty-inventory response as
        # transient, but never treat it as proof that the credential dataset
        # exists. Keep polling until the exact owner-scoped ref is visible.
        last_output = "\n".join(lines[:4])[:500]
        empty_inventory = (
            not lines
            or (len(lines) == 1 and lines[0].strip().casefold() in {
                "no datasets found", "no datasets found."
            })
        )
        if empty_inventory and time.monotonic() < deadline:
            print(
                "Kaggle owner inventory has not indexed the run-scoped credential dataset yet; retrying.",
                flush=True,
            )
            time.sleep(5)
            continue
        raise SystemExit(
            f"Kaggle owner dataset inventory page {page} returned no CSV ref header; "
            f"last_output={last_output!r}; refusing GPU acquisition."
        )
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[header_index:]))))
    if any(str(row.get("ref") or "").strip().lower() == target for row in rows):
        print("THORIO_PRIVATE_RUNNER_CREDENTIAL_DATASET_IN_OWNER_INVENTORY", flush=True)
        break
    if len(rows) < 100:
        if time.monotonic() < deadline:
            print(
                "Kaggle owner inventory is valid but the run-scoped credential dataset is not visible yet; retrying.",
                flush=True,
            )
            time.sleep(5)
            continue
        raise SystemExit(
            "Kaggle owner inventory does not contain the run-scoped runner credential dataset "
            "after the visibility wait; refusing GPU acquisition."
        )
    page += 1

print(
    f"THORIO_PRIVATE_RUNNER_CREDENTIAL_DATASET_READY ref={sys.argv[1]} "
    "visibility=private-by-default",
    flush=True,
)
PY
