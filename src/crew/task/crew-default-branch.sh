#!/usr/bin/env bash
# Print the default branch of a remote (default: origin). The answer comes from
# `crew-repo-info.py`, which asks `gh` first and falls back to git, so the definition of "default
# branch" lives in one place: the library, shared with crew-worktree.py and crew-diff.sh.
#
# If the branch cannot be resolved: `main` with a stderr warning, or exit 1 with no output under
# --strict.
set -euo pipefail

strict=0
remote=origin
helper="$(dirname "${BASH_SOURCE[0]}")/crew-repo-info.py"  # its sibling link in ~/.agent/bin

for arg in "$@"; do
  case "$arg" in
    --help)
      echo "usage: crew-default-branch.sh [--strict] [remote]   (prints the remote's default branch; defaults to origin)"
      exit 0
      ;;
    --strict) strict=1 ;;
    -*)
      echo "default-branch.sh: unknown option: $arg" >&2
      exit 2
      ;;
    *) remote="$arg" ;;
  esac
done

branch=$("$helper" --network --remote "$remote" --field default_branch 2>/dev/null || true)

if [ -n "$branch" ]; then
  echo "$branch"
  exit 0
fi

if [ "$strict" = 1 ]; then
  echo "default-branch.sh: no default branch for '$remote'; gh and git both failed" >&2
  exit 1
fi
echo "warning: default branch of '$remote' unknown; assuming main (run: git remote set-head $remote -a)" >&2
echo main
