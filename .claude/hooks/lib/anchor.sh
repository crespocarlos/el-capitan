#!/usr/bin/env bash
# The pipeline anchor line, computed in one place.
#
# `spec-status-reconcile.sh` computes it once at `SessionStart` and caches it; `mode-anchor.sh` prints
# the cached line each turn instead of resolving the task again. The cache records the `SPEC.md` it
# describes, so a newer spec — an approval, a status write — invalidates it and the next turn
# recomputes. A gate stays visible within the session, while an idle turn costs one `-nt` check
# instead of three commands. A branch switch is picked up at the next `SessionStart`.
# shellcheck shell=bash

ANCHOR_CACHE="$HOME/.agent/.anchor"

# Print the anchor line for the active task, or nothing when there is none. A user-turn hook must
# never block a turn, so every failure here is a silent no-op by design (crew-lint: allow-swallow).
anchor_line() {
  local task title status branch
  task=$(~/.agent/bin/crew-tool.py task-context --field task_dir 2>/dev/null) || return 0   # crew-lint: allow-swallow
  [ -n "$task" ] || return 0
  [ -f "$task/SPEC.md" ] || return 0
  title=$(head -1 "$task/SPEC.md" | sed 's/^#* *//' | tr -d '"\]\n[:cntrl:]')
  # Single reader for `## Status` (crew-ls owns the contract). An empty value means the spec has no
  # status set — the anchor says so rather than silently emitting nothing.
  status=$(~/.agent/bin/crew-ls.py --status-file "$task/SPEC.md" 2>/dev/null | tr -d '[:space:]"\][:cntrl:]')   # crew-lint: allow-swallow
  [ -n "$status" ] || status=unset
  branch=$(~/.agent/bin/crew-tool.py repo-facts --field branch 2>/dev/null) || branch=""   # crew-lint: allow-swallow
  printf '[CREW: task="%s" status=%s branch="%s" task_dir="%s"]\n' \
    "$title" "$status" "${branch//\"/}" "${task//\"/}"
}

# Recompute, store, and print the anchor. The file is `<line>` then `<spec path>`, so the freshness
# check needs no parsing; with no active task the cache is removed.
anchor_refresh() {
  local line spec
  line=$(anchor_line)
  spec=$(sed -n 's/.*task_dir="\([^"]*\)"\].*/\1/p' <<<"$line")
  mkdir -p "$(dirname "$ANCHOR_CACHE")" 2>/dev/null || return 0
  if [ -n "$line" ]; then
    printf '%s\n%s\n' "$line" "$spec" > "$ANCHOR_CACHE"
  else
    rm -f "$ANCHOR_CACHE"
  fi
  printf '%s\n' "$line"
}

# The cached anchor while its spec is unchanged, otherwise a fresh one.
anchor_current() {
  local line spec
  if [ -f "$ANCHOR_CACHE" ]; then
    line=$(sed -n 1p "$ANCHOR_CACHE")
    spec=$(sed -n 2p "$ANCHOR_CACHE")
    if [ -n "$line" ] && [ -n "$spec" ] && [ -f "$spec" ] && [ "$ANCHOR_CACHE" -nt "$spec" ]; then
      printf '%s\n' "$line"
      return 0
    fi
  fi
  anchor_refresh
}
