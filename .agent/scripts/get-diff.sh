#!/usr/bin/env bash
# get-diff.sh — resolve base ref and emit diff for crew review/test.
#
# Usage (source, not exec):
#   source get-diff.sh --stat          # sets BASE; prints --stat
#   source get-diff.sh --name-status   # sets BASE; prints --name-status
#   source get-diff.sh --full          # sets BASE, CHANGED_FILES; prints full diff
#   source get-diff.sh --full -- f1 f2 # scoped to specific files
#
# Exports: BASE, DIFF_SOURCE, CHANGED_FILES (--full only)
# Exits 1 (with message to stderr) if no committed branch changes found.

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

  if git diff --quiet "${fork_point}...HEAD" -- "${files[@]}"; then
    cat >&2 <<'EOF'
No committed changes found on this branch. `crew review` reviews branch commits.

Other options:
- Review an open PR: `crew review PR #N`
- Review a spec: `crew review spec`
EOF
    return 1
  fi

  export BASE="$fork_point"
  export DIFF_SOURCE="branch"

  case "$mode" in
    --stat)
      git diff --stat "${fork_point}...HEAD" -- "${files[@]}"
      ;;
    --name-status)
      git diff --name-status "${fork_point}...HEAD" -- "${files[@]}"
      ;;
    --full)
      export CHANGED_FILES
      CHANGED_FILES=$(git diff --name-only "${fork_point}...HEAD" -- "${files[@]}")
      git diff "${fork_point}...HEAD" -- "${files[@]}"
      ;;
    *)
      echo "get-diff: unknown mode '$mode' (use --stat, --name-status, or --full)" >&2
      return 1
      ;;
  esac
}

_get_diff_main "$@"
