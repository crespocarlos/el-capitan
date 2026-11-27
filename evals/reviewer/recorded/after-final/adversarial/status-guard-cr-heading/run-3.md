Assessment: request-changes — the hook re-implements the status reader in awk, and the two parse `## Status` differently. Each difference is a way to change the status read by `read_status` without the hook noticing.

Read beyond the package: `.agent/tools/task/task_status.py`

1. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:27`** — hook parses Status with its own awk, not the contract's `read_status` regex
```
status_of() {
  printf '%s\n' "$1" | awk '/^## Status[ \t]*$/ { f = 1; next } f && /^#/ { exit } f && NF { ... }'
```
`task_status.py` says "hooks and tools must not re-implement it", and the two parsers disagree in three ways.
- **CRLF:** the regex accepts `## Status\r\n`, but awk's `$` does not match before the `\r`. A Write on a spec with no Status section, or an empty one, can add `## Status\r\nAPPROVED`. The hook sees `''` before and `''` after and allows it, while `read_status` returns APPROVED.
- **Duplicate headings:** awk stops at the first `## Status` heading, and if the next line starts with `#` it returns empty. The regex keeps searching and matches a second `## Status\nAPPROVED` further down. An Edit that appends this passes the hook and moves the status.
- **Blank line after the heading:** awk skips it and reads the value, while the regex reads it as unset. The hook's before and after values can then disagree with what the tools see.

Gate 1 can therefore be bypassed with an Edit or Write that the hook allows.
Fix: have the hook call the Python reader on both texts, for example `python3 -I -c` importing `task_status.STATUS` and applying it to stdin. Alternatively, run `read_status` on a temp file holding the post-edit content.

2. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:39`** — an empty Write skips the check
```
written=$(hook_field content)
...
if [ -n "$written" ]; then
```
A Write with empty `content` leaves `written` empty, so the whole comparison is skipped. The spec, status included, is wiped to nothing and the guard says nothing. The owner check below may still run. An empty `content` is also indistinguishable from a missing `content` field, so a parse failure of the hook input skips the guard silently.
Fix: take the check path whenever the tool is Write, whatever `content` holds. Compare against an empty status, and fail closed if the field is absent.

3. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:30`** — an Edit whose `old_string` is empty is treated as a Write
```
if [ -n "$old_string" ]; then
```
The Edit-versus-Write branch is chosen by whether `old_string` is non-empty. An Edit with an empty `old_string` falls into the Write branch and reads `content`, which is empty, so the check is skipped.
Fix: branch on the tool name, or on whether the `old_string` field is present, not on its value.