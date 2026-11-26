#!/usr/bin/env bash
# Applies the spec status policy at session start, prints changes, failures, the unreviewed-done
# count, and refreshes the cached pipeline anchor that `mode-anchor.sh` prints each turn.
set -uo pipefail
HOOK_NAME=spec-status
# shellcheck source=lib/hook.sh
. "$(dirname "$0")/lib/hook.sh"
# shellcheck source=lib/anchor.sh
. "$(dirname "$0")/lib/anchor.sh"

# Not `set -e`: a missing tool is reported and the session continues.
tool="$HOME/.agent/bin/crew-task.py"
if [ ! -x "$tool" ]; then
  printf 'spec-status: reconcile failed (%s missing; re-run install.sh from your el-capitan checkout)\n' "$tool"
  exit 0
fi
err=$(mktemp)
trap 'rm -f "$err"' EXIT
out=$(python3 "$tool" reconcile --apply 2>"$err")
rc=$?
if [ "$rc" -ne 0 ]; then
  printf 'spec-status: reconcile failed (exit %s: %s)\n' "$rc" "$(head -n 1 "$err")"
  anchor_refresh >/dev/null
  exit 0
fi
failure=$(grep -m1 '^error:' "$err") || true
[ -n "$failure" ] && printf 'spec-status: reconcile failed (%s)\n' "${failure#error: }"
applied=$(grep '^applied:' <<<"$out") || true
names() { awk -v h="$1" 'index($0,h)==1{f=1;next} /^[a-z]/{f=0} f && /^  /{sub(/^  /,""); sub(/\t.*/,""); print}' <<<"$out" | paste -sd ',' - | sed 's/,/, /g'; }
ready=$(names 'ready to open PR')
stalled=$(names 'stalled IMPLEMENTING')
unreviewed=$(awk '/^done without review pass/{f=1;next} /^[a-z]/{f=0} f && /^  /{n++} END{print n+0}' <<<"$out")
if [ -n "$applied" ]; then
  printf 'spec-status: %s\n' "$(sed 's/^applied: //' <<<"$applied" | paste -sd ';' -)"
fi
[ -n "$ready" ] && printf 'spec-status: %s ready to open PR: %s\n' "$(tr ',' '\n' <<<"$ready" | wc -l | tr -d ' ')" "$ready"
[ -n "$stalled" ] && printf 'spec-status: %s stalled IMPLEMENTING: %s\n' "$(tr ',' '\n' <<<"$stalled" | wc -l | tr -d ' ')" "$stalled"
if [ "${unreviewed:-0}" -gt 0 ]; then
  printf 'spec-status: %s done spec(s) lack a review pass; run crew-ls --reconcile to list\n' "$unreviewed"
fi
# The anchor is refreshed after reconcile, so it reflects the statuses this session just applied.
anchor_refresh >/dev/null

# Pending decisions are surfaced here because nothing else can: a subagent that produced them could
# not ask, and a turn already asked once is never asked again. One line, no import — importing stays
# a named decision.
inbox_tool="$HOME/.agent/bin/crew-inbox.py"
if [ -x "$inbox_tool" ]; then
  pending=$(python3 "$inbox_tool" 2>/dev/null | head -1)
  case "$pending" in
    "inbox: empty"|"") ;;
    *) printf '%s; run crew-mem.py import-inbox <file>\n' "$pending" ;;
  esac
fi
exit 0
