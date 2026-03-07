#!/usr/bin/env bash
set -euo pipefail

# Resolve or create a git worktree for a branch.
#
# Usage:
#   resolve-worktree <branch>          # resolve existing or create from fetched remote
#   resolve-worktree -b <branch> <base> # create new branch from base (for crew-implement)
#
# Output: prints the worktree path to stdout.
# If already in the correct worktree, prints the current directory.

usage() {
  echo "Usage: resolve-worktree [-b] <branch> [base]" >&2
  exit 1
}

CREATE_NEW=false
if [[ "${1:-}" == "-b" ]]; then
  CREATE_NEW=true
  shift
fi

BRANCH="${1:?Branch name required}"
BASE="${2:-}"

REPO_NAME=$(basename "$(git rev-parse --show-toplevel)")
WORKTREE_DIR="../${REPO_NAME}-$(echo "$BRANCH" | tr '/' '-')"

CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || true)
if [[ "$CURRENT_BRANCH" == "$BRANCH" ]]; then
  pwd
  exit 0
fi

EXISTING=$(git worktree list --porcelain \
  | grep -B2 "branch refs/heads/$BRANCH" \
  | grep "^worktree " \
  | sed 's/^worktree //' || true)

if [[ -n "$EXISTING" ]]; then
  echo "$EXISTING"
  exit 0
fi

if [[ "$CREATE_NEW" == true ]]; then
  [[ -z "$BASE" ]] && { echo "Error: -b requires a base ref" >&2; exit 1; }
  git worktree add -b "$BRANCH" "$WORKTREE_DIR" "$BASE" >&2
else
  git fetch origin "$BRANCH" >&2
  git worktree add "$WORKTREE_DIR" "origin/$BRANCH" >&2
fi

echo "$WORKTREE_DIR"
