#!/usr/bin/env bash
# Applies the spec status policy at session start, prints changes, failures, the PRs it recorded,
# the tasks ready to mark done, and refreshes the cached pipeline anchor that `mode-anchor.sh` prints each turn.
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
# The branch-PR lookups share one 3-second budget so a session never waits on GitHub; the rest wait
# for the next session (a cached answer is kept 24 hours).
out=$("$tool" reconcile --apply --pr-budget 3 2>"$err")
rc=$?
if [ "$rc" -ne 0 ]; then
  printf 'spec-status: reconcile failed (exit %s: %s)\n' "$rc" "$(head -n 1 "$err")"
  anchor_refresh >/dev/null
  exit 0
fi
failure=$(grep -m1 '^error:' "$err") || true
[ -n "$failure" ] && printf 'spec-status: reconcile failed (%s)\n' "${failure#error: }"
applied=$(grep '^applied:' <<<"$out") || true
section() { awk -v h="$1" 'index($0,h)==1{f=1;next} /^[A-Za-z]/{f=0} f && /^  /{sub(/^  /,""); print}' <<<"$out"; }
names() { section "$1" | sed 's/\t.*//' | paste -sd ',' - | sed 's/,/, /g'; }
# `slug<TAB>pr=<url><TAB>...` as `slug (#n)`, or `slug (#n: <third field>)` with a second argument.
with_pr() { section "$1" | awk -F'\t' -v why="${2:-}" '{n=$2; sub(/.*\//,"",n); r=""; if (why != "") r=": " $3; print $1 " (#" n r ")"}' | paste -sd ',' - | sed 's/,/, /g'; }
recorded=$(grep '^recorded PR: ' <<<"$out") || true
closable=$(with_pr 'ready to mark done')
first=$(section 'ready to mark done' | head -n 1)
blocked_pr=$(with_pr 'PR open, not closable' why)
ready=$(names 'ready to open PR')
stalled=$(names 'stalled IMPLEMENTING')
if [ -n "$applied" ]; then
  printf 'spec-status: %s\n' "$(sed 's/^applied: //' <<<"$applied" | paste -sd ';' -)"
fi
[ -n "$recorded" ] && printf 'spec-status: %s\n' "$(paste -sd ';' - <<<"$recorded")"
unchecked=$(grep -m1 'not checked for a PR yet' <<<"$out") || true
[ -n "$unchecked" ] && printf 'spec-status: %s\n' "$unchecked"
if [ -n "$closable" ]; then
  printf 'spec-status: %s ready to mark done: %s\n' "$(tr ',' '\n' <<<"$closable" | wc -l | tr -d ' ')" "$closable"
  url=$(awk -F'\t' '{sub(/^pr=/,"",$2); print $2}' <<<"$first")
  dir=$(awk -F'\t' '{sub(/^dir=/,"",$3); print $3}' <<<"$first")
  printf 'spec-status: close one with: ~/.agent/bin/crew-task.py mark-done %s --pr-url %s\n' "$dir" "$url"
fi
[ -n "$blocked_pr" ] && printf 'spec-status: %s PR open, not closable: %s\n' "$(tr ',' '\n' <<<"$blocked_pr" | wc -l | tr -d ' ')" "$blocked_pr"
[ -n "$ready" ] && printf 'spec-status: %s ready to open PR: %s\n' "$(tr ',' '\n' <<<"$ready" | wc -l | tr -d ' ')" "$ready"
[ -n "$stalled" ] && printf 'spec-status: %s stalled IMPLEMENTING: %s\n' "$(tr ',' '\n' <<<"$stalled" | wc -l | tr -d ' ')" "$stalled"
# The anchor is refreshed after reconcile, so it reflects the statuses this session just applied.
anchor_refresh >/dev/null

# Pending decisions are surfaced here because nothing else can: a subagent that produced them could
# not ask, and a turn already asked once is never asked again. One line, no import — importing stays
# a named decision.
inbox_tool="$HOME/.agent/bin/crew-inbox.py"
if [ -x "$inbox_tool" ]; then
  pending=$("$inbox_tool" 2>/dev/null | head -1)
  case "$pending" in
    "inbox: empty"|"") ;;
    *) printf '%s; run crew-mem.py import-inbox <file>\n' "$pending" ;;
  esac
fi
exit 0
