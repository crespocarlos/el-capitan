Assessment: request-changes — the hook's awk `status_of` re-implements `task_status.read_status` and disagrees with it, so Gate 1 can be bypassed under `~/.agent/tasks`.

1. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:25`** — `status_of` is not `read_status`; a second `## Status` section bypasses the guard
```
status_of() {
  printf '%s\n' "$1" | awk '/^## Status[ \t]*$/ { f = 1; next } f && /^#/ { exit } f && NF { ...; print; exit }'
}
```
`task_status.STATUS` is `^(## Status[ \t]*\r?\n)([^\n#][^\n]*?)[ \t]*$` with `re.M` and `search`. It takes the first `## Status` heading whose very next line is a non-`#` value line, and it does not skip blank lines. The awk takes the first `## Status` heading only and skips blank lines.

- **Bypass:** a spec has `## Status`, a blank line, then `## Foo`, and later a second `## Status` followed by `DRAFTING`. Python reads the second section. The awk exits at `## Foo` and returns empty both before and after. An Edit that changes the second value to `APPROVED` is allowed, and `read_status` now returns APPROVED.
- **False deny:** with a blank line directly under the first `## Status`, awk reads the next non-blank line, while Python reads `""`.
- **CRLF:** Python accepts `\r?\n` after the heading. In awk, `## Status\r` does not match `[ \t]*$`, so a CRLF file always yields empty and every edit is allowed.

The persona text says hooks must not re-implement the reader, and this is the divergence that rule guards against. This is new code in the diff.

Fix: have the hook call the Python reader, for example `python3 -I -c` importing `task_status.STATUS` on both the on-disk text and the computed result. If it stays in shell, mirror the regex exactly: strip `\r`, require the value on the line right after the heading, and take the first match anywhere in the file.

2. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:35`** — a Write with empty content skips the check
```
written=$(hook_field content)
if [ -n "$written" ]; then disk=$(cat ...)
...
if [ -n "$written" ]; then
```
`written` is used both as the "no comparison needed" sentinel and as the candidate file text. A Write with `content: ""` (or one whose content is only newlines, which `$(...)` strips) clears the whole spec, and the status goes from APPROVED to `""`. The guard does not run, so that Write is allowed. The same happens when an Edit's replacement leaves the file empty.

Fix: decide whether to compare from the tool shape, not from `-n "$written"`. Use a separate `have_written` flag set in both branches, and compare whenever the tool is Edit or Write. Also check that `hook_field` distinguishes a missing field from an empty one.

3. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:30`** — `old_string` that is empty or fails to match is not handled, and the Edit path depends on `old_string` being non-empty
```
if [ -n "$old_string" ]; then ... else written=$(hook_field content)
```
Edit and Write are told apart only by `old_string` being non-empty. A MultiEdit-style payload with an `edits` array has neither `old_string` nor `content`, so it goes through unchecked. If the hook matcher also covers that tool, it bypasses the guard. I could not confirm the matcher from the files I read.

Fix: fail closed. For a tool that is neither a plain Edit nor a plain Write, deny when it targets a task SPEC.md. Alternatively, apply `edits` sequentially before the comparison.