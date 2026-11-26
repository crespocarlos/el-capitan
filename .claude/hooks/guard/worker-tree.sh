#!/usr/bin/env bash
# A live worker's tree: `git checkout`, `git switch`, `git restore` and `git reset --hard` are denied
# in a working tree whose `.crew-worker.lock` is fresh (younger than 6 hours; see task_lock.py). The
# tree is the hook's cwd, or `git -C <path>`, or a leading `cd <path> &&`. Best effort: it does not
# parse every shell form, and a harness without hooks is protected by nothing but the lock's honesty.
# The builder is exempt: CREW_WORKER_TASK equal to the lock's task= (the hook's environment, or an
# inline `CREW_WORKER_TASK=<id>` prefix, which is all a hook can see of the builder's shell).
set -euo pipefail
HOOK_NAME=worker-tree
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/../lib/hook.sh"
hook_input
hook_event
cmd=$(hook_field command)
[ -n "$cmd" ] || hook_allow

STALE_SECONDS=21600
GIT='git(([[:space:]]+-{1,2}[^[:space:];&|]+([[:space:]]+[^[:space:];&|]+)?)*)[[:space:]]+'
CHANGES_TREE="${GIT}(checkout|switch|restore|reset[[:space:]]+--hard)([[:space:]]|\$|;|&|\|)"
# Quoted text is data: `git commit -m "git checkout x"` is a message, not a command.
INSPECT=$(printf '%s' "$cmd" | sed -E "s/'[^']*'/''/g; s/\"[^\"]*\"/\"\"/g")
grep -Eq -- "$CHANGES_TREE" <<<"$INSPECT" || hook_allow

# An absolute or cwd-relative path, with the quotes the shell would drop.
resolve() { case "$1" in /*) printf '%s' "$1" ;; *) printf '%s/%s' "$2" "$1" ;; esac; }
base=$HOOK_CWD
cd_form='^[[:space:]]*cd[[:space:]]+["'"'"']?([^[:space:]"'"'"';&|]+)["'"'"']?[[:space:]]*&&'
c_form='git[[:space:]]+(-[^[:space:]]+[[:space:]]+)*-C[[:space:]]+["'"'"']?([^[:space:]"'"'"';&|]+)'
if [[ $cmd =~ $cd_form ]]; then base=$(resolve "${BASH_REMATCH[1]}" "$HOOK_CWD"); fi
dir=$base
if [[ $cmd =~ $c_form ]]; then dir=$(resolve "${BASH_REMATCH[2]}" "$base"); fi

root=$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null) || hook_allow
lock="$root/.crew-worker.lock"
[ -f "$lock" ] || hook_allow
started=$(awk -F= '$1=="started"{print $2}' "$lock" 2>/dev/null || true)
task=$(awk -F= '$1=="task"{print $2}' "$lock" 2>/dev/null || true)
case "$started" in '' | *[!0-9]*) hook_allow ;; esac
who=${CREW_WORKER_TASK:-}
inline='(^|[[:space:];&|])CREW_WORKER_TASK=["'"'"']?([^[:space:]"'"'"';&|]*)'
if [[ $cmd =~ $inline ]]; then who=${BASH_REMATCH[2]}; fi
if [ -n "$who" ] && [ "$who" = "$task" ]; then hook_allow; fi
age=$(( $(date +%s) - started ))
if [ "$age" -lt "$STALE_SECONDS" ]; then
  # No task id and no removal command: the denied agent cannot tell a live worker from a crashed one.
  hook_deny "A worker holds $root (lock $(( age / 60 )) min old). Do not change its branch from outside: wait, or use git -C on another tree; if you believe the worker has ended, ask the user before removing the lock."
fi
hook_allow
