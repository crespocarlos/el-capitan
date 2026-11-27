Assessment: request-changes — the hook re-implements the status parser instead of using `read_status`'s regex, and the two disagree on CRLF, on `##`-prefixed lines, and on the first non-blank line, so the guard can be bypassed.
Read beyond the package: `.agent/tools/task/task_status.py`

1. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:27`** — awk parser disagrees with `STATUS` regex, so the guard can be bypassed

```
printf '%s\n' "$1" | awk '/^## Status[ \t]*$/ { f = 1; next } f && /^#/ { exit } f && NF { ... print; exit }'
```
`STATUS` requires the value on the line directly after the heading (`\r?\n`, then `[^\n#]`). It does not skip blank lines. awk skips blank lines and takes the first non-blank line. Take a spec that reads `## Status\n\nDRAFTING\n\n## Other\nAPPROVED`, or a CRLF file. In the CRLF case the awk heading match fails, because `\r` is not in `[ \t]`, so both sides come out empty and the check passes. An edit that inserts a line directly under `## Status` then changes what `read_status` returns while awk still sees the old value. For example, an Edit that inserts `APPROVED` before a blank line and the old `DRAFTING` changes the real status and passes the guard. An agent can therefore self-approve Gate 1. This is new code in the diff. The source comment itself says hooks must not re-implement the reader.
Fix: do not parse in awk. Call the real reader, for example `python3 -I -c` importing `task_status.STATUS`, on both the disk text and the written text. Alternatively mirror the regex exactly, including `\r?`, with no blank-line skipping and the `[^\n#]` first character. Also deny whenever the two parsers could disagree.

2. [attention · 4] **`.claude/hooks/check-task-spec-owner.sh:30`** — an empty `old_string` or empty `content` skips the check

```
old_string=$(hook_field old_string)
if [ -n "$old_string" ]; then ... else written=$(hook_field content)
if [ -n "$written" ]; then
```
A Write with empty `content` blanks the whole spec, status included, and `written` is empty so the check is skipped. A MultiEdit-style payload with an `edits` array, if the tool is hooked, has no `old_string` or `content` field at all and passes unchecked. A Write whose `content` came back empty because of a `hook_field` extraction failure is also silently allowed.
Fix: decide by tool name or by field presence rather than by non-emptiness. Treat a Write as always compared. Deny, or fail closed, for payload shapes the hook does not understand.

3. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:33`** — `$(...)` strips trailing newlines, and bash substitution treats `old_string` as a glob pattern

```
written=${disk/"$old_string"/"$new_string"}
```
The quoted pattern is literal, which is fine. But if `old_string` is not found, `written` equals `disk`, the check passes, and the real Edit then fails harmlessly. The remaining risk is that an Edit whose `old_string` matches multiple places without `replace_all` fails, while the hook's first-match assumption is the same as the tool's. This looks mostly fine. The residual risk is that `hook_field` may mangle trailing newlines or escapes in `old_string`, so the simulated result differs from the real one.
Fix: add a test where `old_string` spans the Status line and ends in a newline.

4. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:21`** — the metadata check moved below the status guard, which changes the guard's reach

Previously a task directory without `.task-id` was allowed straight away. Now the status check runs first for every directory with a SPEC.md. That is arguably intended, but a Status edit to a legitimate non-owner-tracked spec, such as one created by a builder before `.task-id` exists, is now denied. No path offers a way to move the status there other than `crew-task.py`. Confirm that `crew-task.py` can handle such directories.