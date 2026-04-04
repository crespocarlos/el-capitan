#!/usr/bin/env bash
# get-diff.sh — resolve and emit a git diff for the current branch.
#
# Resolves the diff source in priority order:
#   1. committed  — changes on the branch (git diff BASE..HEAD)
#   2. (branch has no commits → stop with a non-zero exit and a message)
#
# Usage:
#   get-diff.sh [--stat | --name-status | --name-only | --full] [-- <files...>]
#
# Flags:
#   --stat         git diff --stat   (file summary, default)
#   --name-status  git diff --name-status
#   --name-only    git diff --name-only
#   --full         full diff (no extra flags)
#   -- <files>     restrict to specific files
#
# Output:
#   Diff content on stdout.
#   Exports DIFF_SOURCE=committed (or exits 1 with an error message on stderr).
#
# Examples:
#   source ~/.agent/scripts/get-diff.sh --stat          # metadata pass
#   source ~/.agent/scripts/get-diff.sh --full          # full diff
#   source ~/.agent/scripts/get-diff.sh --full -- src/  # scoped to src/

set -euo pipefail

MODE="--stat"
FILES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --stat|--name-status|--name-only) MODE="$1"; shift ;;
    --full) MODE=""; shift ;;
    --) shift; FILES=("$@"); break ;;
    *) echo "get-diff.sh: unknown flag: $1" >&2; exit 1 ;;
  esac
done

# Resolve base ref — prefer upstream/main for forks, fall back to origin/main.
# Fetch the ref first so the merge-base is computed against the current remote
# state, not a stale local copy. A stale upstream/main is the most common cause
# of the merge-base landing far back and pulling in thousands of unrelated files.
_base_ref=""
_base_remote=""
_base_branch=""
for _candidate in "upstream main" "origin main" "upstream HEAD" "origin HEAD"; do
  _r=${_candidate%% *}
  _b=${_candidate##* }
  if git remote get-url "$_r" >/dev/null 2>&1; then
    _base_ref="$_r/$_b"
    _base_remote="$_r"
    _base_branch="$_b"
    break
  fi
done

if [ -z "$_base_ref" ]; then
  echo "get-diff.sh: no remote base ref found (tried upstream, origin)" >&2
  exit 1
fi

# Fetch silently to ensure the ref is current
git fetch "$_base_remote" "$_base_branch" --quiet 2>/dev/null || true

BASE=$(git merge-base HEAD "$_base_ref" 2>/dev/null) \
  || { echo "get-diff.sh: could not determine merge base against $_base_ref" >&2; exit 1; }

if [ -n "$(git diff "$BASE"..HEAD --stat 2>/dev/null)" ]; then
  export DIFF_SOURCE=committed
  if [ "${#FILES[@]}" -gt 0 ]; then
    git diff $MODE "$BASE"..HEAD -- "${FILES[@]}"
  else
    git diff $MODE "$BASE"..HEAD
  fi
else
  echo "get-diff.sh: no committed changes on this branch (merge base: $BASE)" >&2
  exit 1
fi
