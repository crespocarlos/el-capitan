#!/usr/bin/env bash
# Run the Ruff version pinned in ruff.toml (`required-version`), so local runs and CI agree.
# Usage: bash evals/ruff.sh check .   (any ruff arguments; uvx when present, else pipx)
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(sed -n 's/^required-version = "==\([0-9.]*\)"$/\1/p' "$root/ruff.toml")"
if [ -z "$version" ]; then
    echo "ruff.sh: no required-version in $root/ruff.toml" >&2
    exit 2
fi
cd "$root"
if command -v uvx >/dev/null 2>&1; then
    exec uvx "ruff@$version" "$@"
elif command -v pipx >/dev/null 2>&1; then
    exec pipx run "ruff==$version" "$@"
fi
echo "ruff.sh: install uv (uvx) or pipx to run ruff $version" >&2
exit 2
