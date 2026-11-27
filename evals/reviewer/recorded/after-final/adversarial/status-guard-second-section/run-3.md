Assessment: request-changes — the hook re-implements `## Status` parsing in awk instead of using `task_status.STATUS`, and the two disagree on inputs an agent can write, so the guard can be bypassed.

Read beyond the package: `.agent/tools/task/task_status.py`

1. [blocking · 5] **`.claude/hooks/check-task-spec-owner.sh:27`** (h1) — A second `## Status` section bypasses the guard because the awk parser and `read_status` pick different sections
```
status_of() {
  printf '%s\n' "$1" | awk '/^## Status[ \t]*$/ { f = 1; next } f && /^#/ { exit } f && NF { ...print; exit }'
```
`STATUS` in `task_status.py` requires the value on the line right after the header (`\n([^\n#][^\n]*?)`). A blank line after the header fails that match, so `STATUS.search` moves on to a later `## Status` header. The awk skips blank lines and takes the first section's first non-blank line. A Write with `## Status\n\nDRAFTING\n…\n## Status\nAPPROVED` leaves the hook seeing DRAFTING→DRAFTING and allows it, while `read_status` returns APPROVED. An Edit that inserts a blank line after the header, when a later `## Status` already exists, does the same. A background builder can therefore self-approve and skip Gate 1.
Fix: don't re-implement the parser. Run the real `task_status.STATUS` on both texts, for example with `python3 -I -c` calling a small helper in `task_status.py` that takes text instead of a path. Alternatively, mirror it exactly in awk: the value must be on the immediately next line, must not start with `#`, and the search continues past a failed header.

2. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:27`** (h1) — CRLF content makes the awk header match fail, so Status changes go undetected
```
awk '/^## Status[ \t]*$/ { f = 1; next } ...
```
`STATUS` accepts `## Status\r\n`, but in awk the trailing `\r` stops `^## Status[ \t]*$` from matching. In a CRLF file, or a Write with CRLF content, both `before` and `after` come out empty and compare equal, while `read_status` sees the real value. Changing DRAFTING to APPROVED passes.
Fix: strip `\r` before matching, or use the shared Python reader as in finding 1.

3. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:39`** — An empty result skips the comparison entirely
```
if [ -n "$written" ]; then
  before=$(status_of "$disk")
```
An Edit that makes the whole file empty, or a Write with empty `content`, leaves `written` empty, so the status comparison is skipped. That could be used to wipe the Status. Also, `hook_field` returns "" for missing fields, so a tool payload shape the hook doesn't recognize, such as MultiEdit with an `edits` array, passes unguarded. Check that every Edit and Write variant allowed under `~/.agent/tasks` is covered.
Fix: decide on "is this a write" from the tool name or field presence rather than from non-empty content. Compare statuses even when `written` is empty, and deny or cover tools that carry an `edits` array.