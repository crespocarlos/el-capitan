# Source-only: sets TASK_DIR and CREW_TASK_STATE, and exports CREW_TASK_DIR.
# Reuses a cached CREW_TASK_DIR.
#
# CREW_TASK_STATE distinguishes "no task" from "cannot determine the task":
#   ok    — TASK_DIR points at an active task
#   none  — git state is readable and no task matches this repo+branch
#   error — resolver failed (detached HEAD, no origin remote); stderr is preserved
# Callers that gate on a task must abort on `error` rather than treating it as `none`.
if [ -n "${BASH_VERSION:-}" ] && [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "task-env.sh: source this file; running it sets nothing" >&2
  exit 2
elif [ -n "${ZSH_VERSION:-}" ]; then
  case "${ZSH_EVAL_CONTEXT:-}" in
    *:file*) ;;
    *) echo "task-env.sh: source this file; running it sets nothing" >&2; exit 2 ;;
  esac
fi

if [ -n "${CREW_TASK_DIR:-}" ]; then
  TASK_DIR="$CREW_TASK_DIR"
  CREW_TASK_STATE="${CREW_TASK_STATE:-ok}"
else
  _crew_err=$(~/.agent/bin/resolve-task-dir.py 2>&1 >/tmp/.crew-task-dir.$$)
  _crew_rc=$?
  TASK_DIR=$(cat /tmp/.crew-task-dir.$$ 2>/dev/null)
  rm -f /tmp/.crew-task-dir.$$
  case $_crew_rc in
    0) if [ -n "$TASK_DIR" ]; then
         CREW_TASK_STATE=ok
         export CREW_TASK_DIR="$TASK_DIR"
       else
         CREW_TASK_STATE=none
       fi ;;
    *) CREW_TASK_STATE=error
       TASK_DIR="" ;;
  esac
  # Resolver warnings on a *successful* run say which task was chosen among several, or
  # that a spec could not be read — the ambiguity a later command must not hide.
  [ -z "$_crew_err" ] || printf '%s\n' "$_crew_err" >&2
  unset _crew_err _crew_rc
fi
export CREW_TASK_STATE
