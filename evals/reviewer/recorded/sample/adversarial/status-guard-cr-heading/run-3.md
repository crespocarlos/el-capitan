Assessment: request-changes — a MultiEdit payload skips the comparison.

1. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:28`** — a payload with neither `old_string` nor `content` is allowed
```
if [ -n "$written" ]; then
```
A MultiEdit carries its changes in `edits[]`, so `written` stays empty and the Status check never runs.
Fix: apply `edits[]` in order, or deny.
