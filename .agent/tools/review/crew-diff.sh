#!/usr/bin/env bash
# crew-diff.sh — resolve base ref and emit diff for crew review/test.
#
# Usage (source, not exec):
#   source crew-diff.sh --stat          # sets BASE; prints --stat
#   source crew-diff.sh --name-status   # sets BASE; prints --name-status
#   source crew-diff.sh --full          # sets BASE, CHANGED_FILES; prints full diff
#   source crew-diff.sh --full -- f1 f2 # scoped to specific files
#
# Exports: BASE, DIFF_SOURCE (branch|branch+worktree|worktree), CHANGED_FILES (--full only)
#
# `crew review` is the gate *before* the commit (`pipeline.md`: "the quality gate between
# implementation and commit"), so both committed branch work and uncommitted work are reviewable, and
# a branch can have both at once.
#
# The diff is always `<fork-point>` vs the working tree, never `<fork>...HEAD`: the three-dot form
# compares two commits and silently drops every staged or unstaged change, which is exactly the state
# a pre-commit review runs in. `DIFF_SOURCE` still reports which halves contributed, because a
# reviewer benefits from knowing whether it is looking at committed or pending work.
# Exits 1 only when there is nothing to review at all.

_get_diff_base() {
  # upstream/main first (forks), then origin/main, origin/master, HEAD~1 fallback
  for ref in upstream/main upstream/master origin/main origin/master; do
    if git rev-parse --verify "$ref" >/dev/null 2>&1; then
      echo "$ref"; return
    fi
  done
  echo "HEAD~1"
}

_get_diff_main() {
  local mode="$1"; shift
  local files=()
  if [[ "${1:-}" == "--" ]]; then
    shift; files=("$@")
  fi

  local base fork_point
  base=$(_get_diff_base)
  fork_point=$(git merge-base --fork-point "$base" HEAD 2>/dev/null \
    || git merge-base "$base" HEAD 2>/dev/null)

  if [[ -z "$fork_point" ]]; then
    echo "get-diff: could not determine fork point from $base" >&2
    return 1
  fi

  # One range for every case: the fork point against the working tree, so committed and uncommitted
  # work are both visible. `DIFF_SOURCE` reports which halves are non-empty: `committed` compares the
  # fork point to HEAD, `pending` compares HEAD to the working tree.
  local range="$fork_point" committed pending
  committed=$(git diff --quiet "${fork_point}...HEAD" -- "${files[@]}" && echo no || echo yes)
  pending=$(git diff --quiet HEAD -- "${files[@]}" && echo no || echo yes)
  # The emitted diff is fork-to-tree, so emptiness is decided on that range: two non-empty halves can
  # cancel (a commit reverted in the working tree) and leave nothing to review.
  if git diff --quiet "$range" -- "${files[@]}"; then
    committed=no pending=no
  fi
  case "$committed$pending" in
    yesyes) export DIFF_SOURCE="branch+worktree" ;;
    yesno)  export DIFF_SOURCE="branch" ;;
    noyes)  export DIFF_SOURCE="worktree" ;;
    *)
      cat >&2 <<'EOF'
No changes found on this branch: no commits since the fork point, and nothing staged or modified.
`crew review` reviews branch commits and uncommitted work.

Other options:
- Review an open PR: `crew review PR #N`
- Review a spec: `crew review spec`
EOF
      return 1
      ;;
  esac

  export BASE="$fork_point"

  case "$mode" in
    --stat)
      git diff --stat "$range" -- "${files[@]}"
      ;;
    --name-status)
      git diff --name-status "$range" -- "${files[@]}"
      ;;
    --full)
      CHANGED_FILES=$(git diff --name-only "$range" -- "${files[@]}")
      export CHANGED_FILES
      git diff "$range" -- "${files[@]}"
      ;;
    *)
      echo "get-diff: unknown mode '$mode' (use --stat, --name-status, or --full)" >&2
      return 1
      ;;
  esac
}

_get_diff_main "$@"
