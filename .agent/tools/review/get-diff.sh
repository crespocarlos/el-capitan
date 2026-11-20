#!/usr/bin/env bash
# Deprecated alias: use crew-diff.sh instead. Removed one release after the rename.
#
# crew-diff.sh is sourced, not executed: it exports BASE, DIFF_SOURCE, and CHANGED_FILES into the
# caller. `exec` would replace the caller's shell, so a sourced invocation sources the replacement
# instead and keeps the exports. An executed invocation behaves like the command it replaced.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="$here/crew-diff.sh"
echo "warning: get-diff.sh is deprecated; use crew-diff.sh instead" >&2
if [ ! -f "$target" ]; then
  echo "error: replacement missing: $target" >&2
  exit 2
fi
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  source "$target" "$@"
  return
fi
exec bash "$target" "$@"
