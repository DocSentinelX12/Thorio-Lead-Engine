#!/usr/bin/env python3
"""Delete one run-scoped Thorio Kaggle resource only after owner inventory confirms it exists."""
from __future__ import annotations

import csv
import io
import os
import re
import subprocess
import sys


def fail(message: str) -> "NoReturn":
    print(message, file=sys.stderr)
    raise SystemExit(1)


def run_kaggle(args: list[str]) -> str:
    result = subprocess.run(
        ["kaggle", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        fail(f"Kaggle CLI command failed ({' '.join(args[:3])}): {detail}")
    return result.stdout or ""


def parse_inventory(output: str, resource_type: str, page: int) -> list[dict[str, str]]:
    lines = [line for line in output.splitlines() if line.strip()]
    header = next(
        (index for index, line in enumerate(lines) if line.strip().lower().startswith("ref,")),
        None,
    )
    if header is None:
        preview = " | ".join(lines[:3]) or "<empty response>"
        fail(
            f"Kaggle {resource_type} inventory page {page} returned no CSV header; "
            f"refusing cleanup. Response preview: {preview}"
        )
    return list(csv.DictReader(io.StringIO("\n".join(lines[header:]))))


def main() -> None:
    if len(sys.argv) != 3:
        fail("Usage: delete-kaggle-owned-resource.sh datasets|kernels OWNER/SLUG")
    resource_type, resource_ref = sys.argv[1:]
    username = os.environ.get("KAGGLE_USERNAME", "").strip()
    if not username or not os.environ.get("KAGGLE_API_TOKEN", "").strip():
        fail("KAGGLE_USERNAME and KAGGLE_API_TOKEN are required.")
    if resource_type not in {"datasets", "kernels"}:
        fail(f"Unsupported Kaggle resource type: {resource_type}")
    if "/" not in resource_ref:
        fail("Refusing Kaggle cleanup for an invalid resource reference.")
    ref_owner, slug = resource_ref.split("/", 1)
    if not ref_owner or not slug or "/" in slug or ref_owner.casefold() != username.casefold():
        fail("Refusing Kaggle cleanup for a resource outside the authenticated owner.")

    if resource_type == "datasets":
        allowed = re.fullmatch(
            r"thorio-runner-credentials-(?:[0-9]+-[0-9]+|acq-[a-f0-9]{16})",
            slug,
        )
    else:
        allowed = re.fullmatch(
            r"(?:thorio-free-gpu-worker-[0-9]+|thorio-free-gpu-nccl-[0-9]+-rank-[01]|"
            r"thorio-physical-gpu-proof-[0-9]+|thorio-physical-external-gpu-proof-[0-9]+)",
            slug,
        )
    if not allowed:
        fail(f"Refusing deletion outside the run-scoped Thorio {resource_type} naming contract.")

    page = 1
    while True:
        output = run_kaggle(
            [resource_type, "list", "--mine", "--page", str(page), "--page-size", "100", "--csv"]
        )
        rows = parse_inventory(output, resource_type, page)
        if any(str(row.get("ref") or "").strip().casefold() == resource_ref.casefold() for row in rows):
            deleted = subprocess.run(
                ["kaggle", resource_type, "delete", resource_ref, "--yes"],
                capture_output=True,
                text=True,
                check=False,
            )
            if deleted.returncode != 0:
                detail = (deleted.stderr or deleted.stdout or "").strip()
                fail(
                    f"Kaggle resource exists in the owner inventory but deletion failed; "
                    f"refusing to claim cleanup success: {detail}"
                )
            print((deleted.stdout or "").strip())
            print(f"THORIO_KAGGLE_RESOURCE_REMOVED type={resource_type} ref={resource_ref}")
            return
        if len(rows) < 100:
            print(f"THORIO_KAGGLE_RESOURCE_ALREADY_ABSENT type={resource_type} ref={resource_ref}")
            return
        page += 1


if __name__ == "__main__":
    main()
