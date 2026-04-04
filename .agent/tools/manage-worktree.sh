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
#   - Removes worktrees whose remote branch is gone (squash-merge safe)
#   - Removes worktrees whose branch is merged into the default branch (fallback)

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

  git fetch --prune --quiet 2>/dev/null || true

  local main_wt
  main_wt=$(git rev-parse --show-toplevel)

  # Collect branches whose remote tracking ref is gone (squash-merge safe)
  local gone_branches
  gone_branches=$(git branch -vv 2>/dev/null \
    | grep ': gone]' \
    | sed 's/^[* ]*//' \
    | awk '{print $1}' || true)

  while IFS= read -r wt_path; do
    [[ -z "$wt_path" ]] && continue
    [[ "$wt_path" == "$main_wt" ]] && continue

    local wt_branch
    wt_branch=$(git worktree list --porcelain \
      | grep -A2 "^worktree ${wt_path}$" \
      | grep "^branch " \
      | sed 's|^branch refs/heads/||' || true)
    [[ -z "$wt_branch" ]] && continue

    local is_stale=false

    # Primary: remote tracking ref is gone (handles squash-merge)
    if echo "$gone_branches" | grep -qx "$wt_branch" 2>/dev/null; then
      is_stale=true
    fi

    # Fallback: branch is merged via commit ancestry (handles merge commits)
    if [[ "$is_stale" == false ]] && git branch --merged "origin/$default_branch" 2>/dev/null | grep -q "^[[:space:]]*${wt_branch}$"; then
      is_stale=true
    fi

    if [[ "$is_stale" == true ]]; then
      git worktree remove "$wt_path" 2>/dev/null && \
        echo "Pruned stale worktree: $wt_path ($wt_branch)" >&2 || true
      git branch -D "$wt_branch" 2>/dev/null && \
        echo "Deleted local branch: $wt_branch" >&2 || true
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

# Collision guard: runs after $EXISTING is known, before the early-exit.
# Handles the case where $WORKTREE_DIR exists on disk but is not registered for the target branch.
if [ -d "$WORKTREE_DIR" ] && [ -z "$EXISTING" ]; then
  # Check if it belongs to a different branch via worktree registry
  OTHER_BRANCH=$(git worktree list --porcelain \
    | grep -B2 "^worktree $(cd "$WORKTREE_DIR" 2>/dev/null && pwd)$" \
    | grep "^branch " | sed 's|^branch refs/heads/||' || true)
  if [ -n "$OTHER_BRANCH" ]; then
    echo "Error: $WORKTREE_DIR is already a worktree for branch '$OTHER_BRANCH'. Cannot reuse for '$BRANCH'." >&2
    exit 1
  fi
  # Directory exists but not registered as a worktree — append hash suffix to avoid collision
  WORKTREE_DIR="${WORKTREE_DIR}-$(git rev-parse --short HEAD)"
fi

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

echo "$(cd "$WORKTREE_DIR" && pwd)"
