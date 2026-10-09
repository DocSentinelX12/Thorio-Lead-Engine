#!/usr/bin/env bash
set -euo pipefail

: "${KAGGLE_USERNAME:?KAGGLE_USERNAME is required}"
: "${KAGGLE_API_TOKEN:?KAGGLE_API_TOKEN is required}"

owner="${KAGGLE_USERNAME,,}"
prefix="${owner}/thorio-runner-credentials-"
page=1
removed=0

while true; do
  listing="$(kaggle datasets list --mine --search "thorio-runner-credentials-" --page "${page}" --page-size 100 --csv)"
  mapfile -t refs < <(
    printf '%s\n' "${listing}" |
      python -c '
import csv, io, re, sys
rows = [line for line in sys.stdin.read().splitlines() if line.strip()]
header = next((i for i, line in enumerate(rows) if line.strip().lower().startswith("ref,")), None)
if header is None:
    raise SystemExit("Kaggle dataset inventory returned no CSV header; refusing stale credential cleanup.")
for row in csv.DictReader(io.StringIO("\n".join(rows[header:]))):
    ref = str(row.get("ref") or "").strip()
    if not ref:
        continue
    owner, sep, slug = ref.partition("/")
    if sep and owner.lower() and re.fullmatch(r"thorio-runner-credentials-[0-9]+-[0-9]+", slug):
        print(ref)
'
  )
  count="${#refs[@]}"
  for ref in "${refs[@]}"; do
    [[ "${ref,,}" == "${prefix}"* ]] || continue
    if output="$(kaggle datasets delete "${ref}" --yes 2>&1)"; then
      printf '%s\n' "${output}"
      echo "STALE_PRIVATE_RUNNER_CREDENTIAL_DATASET_REMOVED ${ref}"
      removed=$((removed + 1))
    else
      printf '%s\n' "${output}" >&2
      if printf '%s' "${output}" | grep -Eiq 'not found|404'; then
        echo "STALE_PRIVATE_RUNNER_CREDENTIAL_DATASET_ALREADY_ABSENT ${ref}"
      else
        echo "STALE_PRIVATE_RUNNER_CREDENTIAL_DATASET_CLEANUP_FAILED ${ref}" >&2
        exit 1
      fi
    fi
  done
  if (( count < 100 )); then
    break
  fi
  page=$((page + 1))
done

echo "STALE_PRIVATE_RUNNER_CREDENTIAL_DATASETS_CLEANUP_COMPLETE removed=${removed}"
