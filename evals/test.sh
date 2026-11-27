#!/usr/bin/env bash
# Run the test suite with the pinned pytest, pytest-xdist and pytest-timeout, on the `python3` found on PATH.
# Usage: bash evals/test.sh [-n auto] [pytest arguments]   (needs uv; CI installs it with astral-sh/setup-uv)
# Every test fails after `timeout_seconds`, so a hung test is a named failure, not a silent wait; a later
# `--timeout N` argument overrides it.
set -euo pipefail
pytest_version=8.4.2
xdist_version=3.8.0
timeout_version=2.4.0
timeout_seconds=60
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v uvx >/dev/null 2>&1; then
    echo "test.sh: install uv (uvx) to run pytest $pytest_version with pytest-xdist $xdist_version" >&2
    exit 2
fi
python="$(command -v python3)" || { echo "test.sh: python3 is not on PATH" >&2; exit 2; }
cd "$root"
# The TUI's pin (tui/requirements.txt) joins the environment, so its pilot smoke runs with the suite.
exec uvx --python "$python" --with "pytest-xdist==$xdist_version" --with "pytest-timeout==$timeout_version" \
    --with-requirements tui/requirements.txt "pytest==$pytest_version" --timeout "$timeout_seconds" "$@"
