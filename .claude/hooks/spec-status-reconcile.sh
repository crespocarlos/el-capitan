#!/usr/bin/env bash
# Applies the spec status policy at session start; prints changes, failures, and the unreviewed-done count.
set -uo pipefail
tool="$HOME/.agent/bin/crew-ls.py"
if [ ! -x "$tool" ]; then
  printf 'spec-status: reconcile failed (%s missing)\n' "$tool"
  exit 0
fi
err=$(mktemp)
trap 'rm -f "$err"' EXIT
out=$(python3 "$tool" --reconcile --apply 2>"$err")
rc=$?
if [ "$rc" -ne 0 ]; then
  printf 'spec-status: reconcile failed (exit %s: %s)\n' "$rc" "$(head -n 1 "$err")"
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
exit 0
