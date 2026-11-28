#!/usr/bin/env bash
# Run the test suite in the project's dev environment (the `dev` group of pyproject.toml, pinned in uv.lock).
# Usage: bash evals/test.sh [-n auto] [pytest arguments]   (needs uv)
# Every test fails after 60 s, so a hung test is a named failure, not a silent wait; a later `--timeout N`
# overrides it. Tests run offline: an install into a throwaway HOME reuses this uv cache and interpreter.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
command -v uv >/dev/null 2>&1 || { echo "test.sh: install uv to run the suite" >&2; exit 2; }
uv sync --frozen --managed-python --quiet
UV_CACHE_DIR="$(uv cache dir)" UV_PYTHON_INSTALL_DIR="$(uv python dir)" UV_OFFLINE=1 \
    exec uv run --frozen --managed-python pytest --timeout 60 "$@"
