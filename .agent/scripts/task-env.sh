# Source-only: sets TASK_DIR (empty when there is no active task) and exports CREW_TASK_DIR.
# Reuses a cached CREW_TASK_DIR. Silent on failure; the caller decides what an empty TASK_DIR means.
if [ -n "${BASH_VERSION:-}" ] && [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "task-env.sh: source this file; running it sets nothing" >&2
  exit 2
elif [ -n "${ZSH_VERSION:-}" ]; then
  case "${ZSH_EVAL_CONTEXT:-}" in
    *:file*) ;;
    *) echo "task-env.sh: source this file; running it sets nothing" >&2; exit 2 ;;
  esac
fi

if [ -n "${CREW_TASK_DIR+x}" ]; then
  TASK_DIR="$CREW_TASK_DIR"
elif TASK_DIR=$(~/.agent/bin/resolve-task-dir.py 2>/dev/null); then
  export CREW_TASK_DIR="$TASK_DIR"
else
  TASK_DIR=""
fi
