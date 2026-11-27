#!/usr/bin/env bash
# Run the test suite with the pinned pytest and pytest-xdist, on the `python3` found on PATH.
# Usage: bash evals/test.sh [-n auto] [pytest arguments]   (needs uv; CI installs it with astral-sh/setup-uv)
set -euo pipefail
pytest_version=8.4.2
xdist_version=3.8.0
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v uvx >/dev/null 2>&1; then
    echo "test.sh: install uv (uvx) to run pytest $pytest_version with pytest-xdist $xdist_version" >&2
    exit 2
fi
python="$(command -v python3)" || { echo "test.sh: python3 is not on PATH" >&2; exit 2; }
cd "$root"
exec uvx --python "$python" --with "pytest-xdist==$xdist_version" "pytest==$pytest_version" "$@"
