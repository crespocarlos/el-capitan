Assessment: request-changes — the hook re-implements the status parser in awk, and the two parsers disagree on inputs an agent can write, so the Gate 1 guard can be bypassed.

1. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:25`** — `status_of` is a second parser that disagrees with `task_status.STATUS`
```
status_of() {
  printf '%s\n' "$1" | awk '/^## Status[ \t]*$/ { f = 1; next } f && /^#/ { exit } f && NF { ... print; exit }'
```
`task_status.py:7` says "hooks and tools must not re-implement it", and this hook does. The two disagree in two ways:
- **Blank lines.** Python's `STATUS` requires the value on the line right after the heading, so a blank line there gives `""`. Awk skips blank lines and takes the first non-blank line.
- **CRLF.** Python accepts `\r?` after the heading. Awk's `^## Status[ \t]*$` doesn't match `## Status\r`, so it returns empty.

Concrete bypass: take a spec whose first `## Status` is followed by a blank line, with `DRAFTING` below it. Edit it to append a second `## Status\nAPPROVED` section.
- Awk still reads `DRAFTING` from the first heading, so `before` equals `after` and the edit is allowed.
- Python skips the first heading, matches the second, and `read_status` returns `APPROVED`. The agent has moved Gate 1.

With a CRLF spec, awk returns empty on both sides, so any status edit passes.

Fix: don't parse in bash. Have the hook call a small Python entry point that imports `task_status.STATUS`, or `read_status` on temp files, for both the before and after text. If it stays in awk, copy the regex semantics exactly (value only on the immediately following line, `\r?`, first match wins), and deny when the document contains more than one `## Status` heading.

2. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:35`** — a Write with empty content skips the guard
```
written=$(hook_field content)
if [ -n "$written" ]; then disk=$(cat ...)
...
if [ -n "$written" ]; then
```
A Write with `content: ""` truncates SPEC.md, so the status goes from `APPROVED` to unset. The `-n` test treats it as "nothing written" and skips the comparison. The same happens when the content is only newlines, because `$(...)` strips them. Likewise, an Edit whose result is empty skips the guard, and the check is also skipped if `hook_field` yields an empty string for a missing field.

Fix: tell "Write" from "Edit" by whether `old_string` or the `content` key is present, not by whether the value is non-empty. Always compute `before` and `after` for a Write, treating empty content as a document with no status.

3. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:30`** — an Edit that fails to apply is compared as a no-op
```
written=${disk/"$old_string"/"$new_string"}
```
If `old_string` isn't found, `written` equals `disk` and the guard passes, which is correct because the tool will reject that edit. But `disk` and `written` are both stripped of trailing newlines by `$(...)`. When `old_string` is only whitespace or newlines, `old_string=$(hook_field old_string)` is also normalised if `hook_field` uses `$(...)`. The simulated edit then diverges from what the tool actually applies, so the guard evaluates a different document than the one written. I couldn't read `lib/hook.sh`, so I couldn't confirm how `hook_field` handles this.

Fix: simulate the edit on a byte-exact copy, for example with Python reading the real `file_path`, `old_string` and `new_string` from the hook's stdin JSON.