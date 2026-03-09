#!/usr/bin/env bash
set -euo pipefail

# Manage git worktrees: resolve, create, and auto-prune.
#
# Usage:
#   manage-worktree.sh <branch>          # resolve existing or create from fetched remote
#   manage-worktree.sh -b <branch> <base> # create new branch from base (for crew-implement)
#
# Output: prints the worktree path to stdout.
# If already in the correct worktree, prints the current directory.
#
# Side effects:
#   - Prunes orphaned worktree metadata (git worktree prune)
#   - Removes worktrees whose branches are merged into the default branch

usage() {
  echo "Usage: manage-worktree.sh [-b] <branch> [base]" >&2
  exit 1
}

# --- Auto-prune merged worktrees ---

prune_merged_worktrees() {
  git worktree prune 2>/dev/null || true

  local default_branch
  default_branch=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}' || true)
  [[ -z "$default_branch" ]] && return

  git fetch origin "$default_branch" --quiet 2>/dev/null || true

  local main_wt
  main_wt=$(git rev-parse --show-toplevel)

  while IFS= read -r wt_path; do
    [[ "$wt_path" == "$main_wt" ]] && continue

    local wt_branch
    wt_branch=$(git worktree list --porcelain \
      | grep -A2 "^worktree ${wt_path}$" \
      | grep "^branch " \
      | sed 's|^branch refs/heads/||' || true)
    [[ -z "$wt_branch" ]] && continue

    if git branch --merged "origin/$default_branch" 2>/dev/null | grep -q "^[[:space:]]*${wt_branch}$"; then
      git worktree remove "$wt_path" 2>/dev/null && \
        echo "Pruned merged worktree: $wt_path ($wt_branch)" >&2 || true
    fi
  done < <(git worktree list --porcelain | grep "^worktree " | sed 's/^worktree //')
}

prune_merged_worktrees

# --- Parse arguments ---

CREATE_NEW=false
if [[ "${1:-}" == "-b" ]]; then
  CREATE_NEW=true
  shift
fi

BRANCH="${1:?Branch name required}"
BASE="${2:-}"

REPO_NAME=$(basename "$(git rev-parse --show-toplevel)")
WORKTREE_DIR="../worktrees/${REPO_NAME}-$(echo "$BRANCH" | tr '/' '-')"

# Already on the target branch — nothing to do
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || true)
if [[ "$CURRENT_BRANCH" == "$BRANCH" ]]; then
  pwd
  exit 0
fi

# Check for an existing worktree on this branch
EXISTING=$(git worktree list --porcelain \
  | grep -B2 "branch refs/heads/$BRANCH" \
  | grep "^worktree " \
  | sed 's/^worktree //' || true)

if [[ -n "$EXISTING" ]]; then
  echo "$EXISTING"
  exit 0
fi

# Create the worktrees directory if needed
mkdir -p "../worktrees"

if [[ "$CREATE_NEW" == true ]]; then
  [[ -z "$BASE" ]] && { echo "Error: -b requires a base ref" >&2; exit 1; }
  git worktree add -b "$BRANCH" "$WORKTREE_DIR" "$BASE" >&2
else
  git fetch origin "$BRANCH" >&2
  git worktree add "$WORKTREE_DIR" "origin/$BRANCH" >&2
fi

echo "$WORKTREE_DIR"
