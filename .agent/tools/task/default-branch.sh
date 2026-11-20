#!/usr/bin/env bash
# Deprecated alias: use crew-default-branch.sh instead. Removed one release after the rename.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="$here/crew-default-branch.sh"
echo "warning: default-branch.sh is deprecated; use crew-default-branch.sh instead" >&2
if [ ! -f "$target" ]; then
  echo "error: replacement missing: $target" >&2
  exit 2
fi
exec bash "$target" "$@"
