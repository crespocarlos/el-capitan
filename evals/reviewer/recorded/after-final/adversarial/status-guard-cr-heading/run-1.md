Assessment: request-changes — the hook decides with its own awk parser, not `task_status.read_status`, and the two disagree. One Edit can set the status to APPROVED while the hook sees no change.

Read beyond the package: `.agent/tools/task/task_status.py`

1. [blocking · 5] **`.claude/hooks/check-task-spec-owner.sh:27`** — the awk status parser disagrees with `read_status`, so the guard can be bypassed
```
status_of() { ... '/^## Status[ \t]*$/ { f = 1; next } f && /^#/ { exit } f && NF { ...print; exit }'
```
`STATUS` in `task_status.py` requires the value on the line right after the heading (`\n([^\n#]...)`). If a blank line follows, that heading does not match and the regex moves on to a later `## Status` heading. The awk skips blank lines and takes the first non-blank line under the first heading. Take a spec whose status is DRAFTING. An Edit replaces `## Status\nDRAFTING` with `## Status\n\nDRAFTING\n\n## Status\nAPPROVED`. The hook reads DRAFTING before and after, so it allows the edit. `read_status` skips the first heading, matches the second, and returns APPROVED. Gate 1 is bypassed in one edit.
CRLF is a second divergence. The regex accepts `\r?\n` after the heading, but the awk's `[ \t]*$` rejects a trailing `\r`. On a CRLF spec the hook finds no Status section, so it reports "none" before and after and allows every status change.
Fix: do not reimplement the parser. Call `task_status.STATUS` through python on the before and after text, for example `python3 -I -c` with the text on stdin. Failing that, make the awk match the regex exactly: the value must be on the immediately following line, tolerate `\r`, and use the first matching heading. Also deny any edit that adds a second `## Status` heading.

2. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:39`** — an empty Write skips the check and erases the status
```
if [ -n "$written" ]; then
  before=$(status_of "$disk")
```
A Write with empty `content` leaves `written` empty, so the comparison is skipped. The same happens for an Edit whose result is empty. The file is truncated and `read_status` returns "". A Write or Edit that deletes the status section is compared as "none" and is denied, but a truncation is not. Gate state is lost, and the state is inconsistent with what `crew-task.py` expects.
Fix: decide whether to compare by whether the tool is Write or Edit, not by `written` being non-empty. Always compute `before` and `after` for an existing SPEC.md.

3. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:31`** — the guard only handles the `old_string` and `content` shapes
```
if [ -n "$old_string" ]; then ... else written=$(hook_field content)
```
Any other tool-input shape (for example a MultiEdit `edits` array, or an Edit with empty `old_string`) goes down the `content` path. `content` is empty there, so the guard is skipped. Install allows everything under `~/.agent/tasks`, so the unprompted path stays open for those shapes.
Fix: deny, or run the full comparison, for any tool input that is not a recognised Write or Edit shape on a task SPEC.md. Also check that the hook matcher covers MultiEdit.