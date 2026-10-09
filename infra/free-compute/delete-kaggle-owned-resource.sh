#!/usr/bin/env bash
set -euo pipefail

: "${KAGGLE_USERNAME:?KAGGLE_USERNAME is required}"
: "${KAGGLE_API_TOKEN:?KAGGLE_API_TOKEN is required}"
resource_type="${1:?usage: delete-kaggle-owned-resource.sh datasets|kernels OWNER/SLUG}"
resource_ref="${2:?usage: delete-kaggle-owned-resource.sh datasets|kernels OWNER/SLUG}"

owner="${KAGGLE_USERNAME,,}"
ref_owner="${resource_ref%%/*}"
slug="${resource_ref#*/}"
if [[ "${resource_ref}" != */* || "${slug}" == */* || "${ref_owner,,}" != "${owner}" ]]; then
  echo "Refusing Kaggle cleanup for a resource outside the authenticated owner." >&2
  exit 1
fi

case "${resource_type}" in
  datasets)
    if [[ ! "${slug}" =~ ^thorio-runner-credentials-([0-9]+-[0-9]+|acq-[a-f0-9]{16})$ ]]; then
      echo "Refusing deletion of a dataset outside the run-scoped Thorio credential naming contract." >&2
      exit 1
    fi
    ;;
  kernels)
    if [[ ! "${slug}" =~ ^(thorio-free-gpu-worker-[0-9]+|thorio-free-gpu-nccl-[0-9]+-rank-[01]|thorio-physical-gpu-proof-[0-9]+|thorio-physical-external-gpu-proof-[0-9]+)$ ]]; then
      echo "Refusing deletion of a kernel outside the run-scoped Thorio GPU naming contract." >&2
      exit 1
    fi
    ;;
  *)
    echo "Unsupported Kaggle resource type: ${resource_type}" >&2
    exit 1
    ;;
esac

page=1
while true; do
  if ! listing="$(kaggle "${resource_type}" list --mine --page "${page}" --page-size 100 --csv 2>&1)"; then
    printf 'Could not enumerate Kaggle %s inventory before cleanup: %s\n' "${resource_type}" "${listing}" >&2
    exit 1
  fi
  parsed="$(printf '%s\n' "${listing}" | python - "${resource_ref}" <<'PY'
import csv
import io
import sys

target = sys.argv[1]
lines = [line for line in sys.stdin.read().splitlines() if line.strip()]
header = next((i for i, line in enumerate(lines) if line.strip().lower().startswith("ref,")), None)
if header is None:
    preview = " | ".join(lines[:3]) or "<empty response>"
    raise SystemExit(f"Kaggle inventory returned no CSV header; refusing cleanup. Response preview: {preview}")
rows = list(csv.DictReader(io.StringIO("\n".join(lines[header:]))))
print(len(rows))
print("FOUND" if any(str(row.get("ref") or "").strip().lower() == target.lower() for row in rows) else "ABSENT")
PY
)"
  row_count="$(printf '%s\n' "${parsed}" | head -n 1)"
  match="$(printf '%s\n' "${parsed}" | tail -n 1)"
  if [[ "${match}" == "FOUND" ]]; then
    if output="$(kaggle "${resource_type}" delete "${resource_ref}" --yes 2>&1)"; then
      printf '%s\n' "${output}"
      printf 'THORIO_KAGGLE_RESOURCE_REMOVED type=%s ref=%s\n' "${resource_type}" "${resource_ref}"
      exit 0
    fi
    printf '%s\n' "${output}" >&2
    if ! verify="$(kaggle "${resource_type}" list --mine --page 1 --page-size 100 --csv 2>&1)"; then
      printf 'Could not recheck Kaggle inventory after delete failure: %s\n' "${verify}" >&2
      exit 1
    fi
    if printf '%s\n' "${verify}" | python - "${resource_ref}" <<'PY'
import csv
import io
import sys

target = sys.argv[1].lower()
lines = [line for line in sys.stdin.read().splitlines() if line.strip()]
header = next((i for i, line in enumerate(lines) if line.strip().lower().startswith("ref,")), None)
if header is None:
    raise SystemExit("Kaggle inventory returned no CSV header after delete failure.")
rows = list(csv.DictReader(io.StringIO("\n".join(lines[header:]))))
raise SystemExit(0 if any(str(row.get("ref") or "").strip().lower() == target for row in rows) else 1)
PY
    then
      echo "Kaggle resource still exists after delete failure; refusing to report cleanup success." >&2
      exit 1
    else
      echo "THORIO_KAGGLE_RESOURCE_ALREADY_ABSENT type=${resource_type} ref=${resource_ref}"
      exit 0
    fi
  fi
  if [[ ! "${row_count}" =~ ^[0-9]+$ ]]; then
    echo "Kaggle inventory parser returned an invalid row count; refusing cleanup." >&2
    exit 1
  fi
  if (( row_count < 100 )); then
    echo "THORIO_KAGGLE_RESOURCE_ALREADY_ABSENT type=${resource_type} ref=${resource_ref}"
    exit 0
  fi
  page=$((page + 1))
done
