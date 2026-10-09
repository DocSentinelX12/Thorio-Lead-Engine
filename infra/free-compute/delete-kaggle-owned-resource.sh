#!/usr/bin/env bash
set -euo pipefail
exec python "$(dirname "$0")/delete-kaggle-owned-resource.py" "$@"
