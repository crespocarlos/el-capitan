Assessment: request-changes — the status guard uses its own awk parser rather than `read_status`, and the two disagree on inputs an agent can produce, so Gate 1 can still be bypassed.
Read beyond the package: `.agent/tools/task/task_status.py`

1. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:27`** — awk status parser disagrees with `task_status.STATUS`, so a second `## Status` section bypasses the guard
```
status_of() {
  printf '%s\n' "$1" | awk '/^## Status[ \t]*$/ { f = 1; next } f && /^#/ { exit } f && NF { ... print; exit }'
```
`STATUS` in task_status.py is `^(## Status[ \t]*\r?\n)([^\n#][^\n]*?)[ \t]*$` with `re.M` and `search`. It needs the value on the line right after the heading and takes the first heading that matches. The awk skips blank lines and reads only the first heading. Take a spec whose first section is `## Status`, a blank line, then `DRAFTING`. An Edit appends a second `## Status` section containing `DONE`. awk reads `DRAFTING` before and after, so the hook allows it. `read_status` skips the first heading (blank line, no match), matches the second, and reports `DONE`. Gate 1 is bypassed, and the diff's own claim that `read_status` is what every tool reads is what makes this work. The reverse also holds: awk can treat an edit as a status change that `read_status` ignores.
Fix: Do not reimplement the parser. Call the Python reader on both texts, for example by importing `task_status.STATUS` in a small `python3 -I` helper fed the before and after text. Failing that, make the awk match the regex exactly: the value must be the very next line, it must not start with `#`, and it must use the first matching heading.

2. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:27`** — CRLF specs make the guard see no status at all
```
/^## Status[ \t]*$/ { f = 1; next }
```
`STATUS` explicitly accepts `\r?\n` after the heading. For a CRLF file the awk line is `## Status\r`, which `[ \t]*$` does not match, so `f` is never set. `status_of` returns empty for both before and after, they compare equal, and any status change goes through. A spec with CRLF endings, or one rewritten with CRLF by a Write, is unguarded.
Fix: Strip `\r` before parsing (`sub(/\r$/, "")`), or use the shared Python reader as in finding 1.

3. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:35`** — an empty Write skips the comparison
```
written=$(hook_field content)
if [ -n "$written" ]; then disk=...
...
if [ -n "$written" ]; then
```
A Write with empty `content` leaves `written` empty, so the check is skipped. The same happens when an Edit's result is empty. Empty `content` truncates SPEC.md and removes the Status section, which `read_status` reports as "" (unset), and the guard never saw the change. `$(...)` also strips trailing newlines, which is harmless here. Whether the owner check below catches the truncation depends on `.task-id`, and that check is only reached if the file has the owner metadata.
Fix: Decide whether to compare on tool type, not on string emptiness. If the tool is Write, always read the disk and compare, treating an empty `content` as a file with no status.