#!/usr/bin/env bash
# A live worker's tree: `git checkout`, `git switch`, `git restore` and `git reset --hard` are denied
# in a working tree whose `.crew-worker.lock` is fresh (younger than 6 hours; see task_lock.py). Each
# segment of the command is judged in its own tree (the hook's cwd, moved by `cd`, then `git -C`), so
# a `-C` on one segment does not move the next. A harness without hooks is protected by nothing but
# the lock's honesty.
# The builder is exempt: CREW_WORKER_TASK equal to the lock's task= (the hook's environment, or an
# inline `CREW_WORKER_TASK=<id>` prefix, which is all a hook can see of the builder's shell).
set -euo pipefail
HOOK_NAME=worker-tree
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_stand_down guard/worker-tree.sh fail-closed
hook_input
hook_event
cmd=$(hook_field command)
[ -n "$cmd" ] || hook_allow

STALE_SECONDS=21600
who=${CREW_WORKER_TASK:-}
inline='(^|[[:space:];&|])CREW_WORKER_TASK=["'"'"']?([^[:space:]"'"'"';&|]*)'
if [[ $cmd =~ $inline ]]; then who=${BASH_REMATCH[2]}; fi
hook_segments "$cmd"
i=0
while [ "$i" -lt "${#HOOK_SEGS[@]}" ]; do
  hook_seg "$i"
  i=$((i + 1))
  hook_git || continue
  case "$GIT_SUB" in
    checkout | switch | restore) ;;
    reset) hook_git_arg '^--hard$' || continue ;;
    *) continue ;;
  esac
  root=$(git -C "$GIT_TREE" rev-parse --show-toplevel 2>/dev/null) || continue
  lock="$root/.crew-worker.lock"
  [ -f "$lock" ] || continue
  started=$(awk -F= '$1=="started"{print $2}' "$lock" 2>/dev/null || true)
  task=$(awk -F= '$1=="task"{print $2}' "$lock" 2>/dev/null || true)
  case "$started" in '' | *[!0-9]*) continue ;; esac
  if [ -n "$who" ] && [ "$who" = "$task" ]; then continue; fi
  age=$(($(date +%s) - started))
  if [ "$age" -lt "$STALE_SECONDS" ]; then
    # No task id and no removal command: the denied agent cannot tell a live worker from a crashed one.
    hook_deny "A worker holds $root (lock $((age / 60)) min old). Do not change its branch from outside: wait, or use git -C on another tree; if you believe the worker has ended, ask the user before removing the lock."
  fi
done
hook_allow
