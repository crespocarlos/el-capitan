#!/usr/bin/env bash
# Run the Ruff version pinned in ruff.toml (`required-version`), so local runs and CI agree.
# Usage: bash evals/ruff.sh check .   or   bash evals/ruff.sh format --check .   (needs uv)
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(sed -n 's/^required-version = "==\([0-9.]*\)"$/\1/p' "$root/ruff.toml")"
if [ -z "$version" ]; then
    echo "ruff.sh: no required-version in $root/ruff.toml" >&2
    exit 2
fi
cd "$root"
exec uvx "ruff@$version" "$@"
