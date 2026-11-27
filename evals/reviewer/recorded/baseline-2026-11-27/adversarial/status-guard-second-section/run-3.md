Assessment: request-changes — the hook re-implements `## Status` parsing in awk instead of using `task_status.read_status`, and the two disagree, so a Write or Edit can move the status past the guard.

1. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:25`** — `status_of` reads a different section than `read_status`, so adding a second `## Status` section bypasses the guard
```
status_of() {
  printf '%s\n' "$1" | awk '/^## Status[ \t]*$/ { f = 1; next } f && /^#/ { exit } f && NF { ...; print; exit }'
}
```
The awk takes the first non-blank line under the first `## Status` heading. `STATUS` in `task_status.py:8` requires the value on the line immediately after a heading. It uses `re.search`, so it moves on to a later `## Status` heading if the first has no value on the next line. Take a spec with `## Status\n\n## Notes`. The awk reads empty. An Edit or Write that appends `## Status\nDONE` leaves the awk reading empty, so before equals after and the hook allows it. `read_status` now returns `DONE`, which is the Gate 1 bypass this change exists to stop.
The same mismatch shows up in two more ways:
- A blank line between the heading and the value: the awk reads `DRAFTING`, Python reads `""`.
- A CRLF heading: the awk heading regex does not match `\r`, Python's does.
The code comment claims `read_status` is what every tool reads, and the file itself says hooks must not re-implement it.
Fix: call Python from the hook, e.g. `python3 -I -c 'import sys; sys.path.insert(0, "<tools>/task"); import task_status; ...'`. It should apply `task_status.STATUS` to the old and new text, or `read_status` on the old file and on a temp file holding the new text. Deny on any difference, and on failure to evaluate.

2. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:35`** — a Write with empty `content` skips the check
```
written=$(hook_field content)
if [ -n "$written" ]; then disk=$(cat ...
...
if [ -n "$written" ]; then
```
`written` is empty both when a Write truncates the file and when an Edit deletes everything, so the whole comparison is skipped. Truncating the SPEC removes its status. `read_status` then returns `""`, which is a status change. Separately, if `hook_field` fails to extract the field, the guard is silently skipped (fail-open).
Fix: key the check on the tool and on whether the field is present, not on non-emptiness. Compare `before` with the status of the empty text, and deny if they differ.

3. [nit · 2] **`.claude/hooks/check-task-spec-owner.sh:30`** — only the single-edit shape is handled
The hook reads `old_string` and `new_string` only. If a multi-edit tool (e.g. `MultiEdit` with an `edits` array) can reach `~/.agent/tasks` through the same hook matcher, its status changes are never examined. This is unverified: I could not read `lib/hook.sh` or the install matcher, so I don't know whether such a tool is routed here.
Fix: confirm the hook matcher covers only Edit and Write, or add handling for the multi-edit shape.