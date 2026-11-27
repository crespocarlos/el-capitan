Assessment: request-changes — the hook re-implements `## Status` parsing in awk, and it disagrees with `task_status.read_status`. A status change that `read_status` sees can pass the hook.

Read beyond the package: `.agent/tools/task/task_status.py`, `.claude/hooks/check-task-spec-owner.sh`

1. [blocking · 5] **`.claude/hooks/check-task-spec-owner.sh:27`** (`status_of`) — the awk parser picks a different status than `read_status`, so a second `## Status` section bypasses the guard
```
printf '%s\n' "$1" | awk '/^## Status[ \t]*$/ { f = 1; next } f && /^#/ { exit } f && NF { ... print; exit }'
```
```
STATUS = re.compile(r"^(## Status[ \t]*\r?\n)([^\n#][^\n]*?)[ \t]*$", re.M)
```
`read_status` only matches a value on the line directly after the header, and it keeps searching later headers if that fails. awk skips blank lines after the header and stops at the next `#` line. Take a spec where the first `## Status` is followed by a blank line or a heading, and a second `## Status\nDRAFTING` appears later. awk reads the first header (empty, or the value past the blank line). `read_status` reads the second one. An Edit that changes only the second section to `APPROVED` leaves the hook's `before` and `after` equal, so it is allowed. Every tool then reads `APPROVED`, and Gate 1 is bypassed by a background builder. The reverse also happens: a blank line after the header makes the hook see a value that `read_status` ignores. The comment in `task_status.py` says hooks must not re-implement the reader, and this does.
Fix: have the hook call the shared reader on both texts, for example `python3 -I -c` importing `task_status.STATUS`, applied to the disk text and the written text through stdin or temp files. Failing that, copy the regex semantics exactly (value on the immediately following line, first matching header).

2. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:27`** — a CRLF header defeats the awk match
```
/^## Status[ \t]*$/
```
The Python regex accepts `\r?\n` after the header. awk's `[ \t]*$` does not accept `\r`. In a CRLF SPEC.md the hook never finds the section, so `before` and `after` are both empty for any status edit. `read_status` still reads the value, so the status changes without a prompt.
Fix: strip `\r` before the awk step (`tr -d '\r'`), or use the shared Python reader as in finding 1.

3. [attention · 4] **`.claude/hooks/check-task-spec-owner.sh:36`** — an empty Write skips the guard
```
written=$(hook_field content)
if [ -n "$written" ]; then ...
```
A Write with empty `content` replaces the spec with an empty file, so the status goes from `APPROVED` to unset. `written` is empty, the comparison is skipped, and the write is allowed. The same happens when an Edit produces an empty result. Also, `$(...)` strips trailing newlines from `old_string`, `new_string` and `content`, so the simulated edit can differ from what Edit actually does.
Fix: track "was a Write or Edit with this field present" in a separate flag instead of testing the content for non-empty. Compare `status_of` unconditionally when a write is happening.