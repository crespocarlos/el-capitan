Assessment: request-changes — the hook re-implements the `## Status` parser that `task_status.read_status` owns, and the two disagree, so the Gate 1 guard can be bypassed.

1. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:27`** — `status_of` parses differently from `task_status.STATUS`, so a status can be changed without the hook noticing
```
status_of() {
  printf '%s\n' "$1" | awk '/^## Status[ \t]*$/ { f = 1; next } f && /^#/ { exit } f && NF { ...print; exit }'
}
```
`task_status.STATUS` is `^(## Status[ \t]*\r?\n)([^\n#][^\n]*?)[ \t]*$`. It reads only the line directly under the heading, and it accepts `\r`. The awk skips blank lines and does not accept `\r`.
- An Edit that inserts a blank line after the heading (`## Status\nAPPROVED` becomes `## Status\n\nAPPROVED`) leaves the hook's value unchanged, so it is allowed. `read_status` then returns `""`, so the status is unset or reset by a hook-approved edit.
- The reverse also holds. A whitespace-only line under the heading makes `read_status` return `""`, while the hook sees the status on the line after it.
- With CRLF line endings the awk never finds the heading, so `before` and `after` are both empty and every status edit passes.

The new header comment names `task_status.read_status` as the one reader, and `task_status.py:7` says "hooks and tools must not re-implement it".

Fix: have the hook call the Python reader. For example, run `python3 -I -c` with `task_status.STATUS` on both the disk text and the written text. Failing that, match the regex exactly, including the immediately-following-line rule and `\r`.

2. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:38`** — a Write with empty content skips the check
```
written=$(hook_field content)
if [ -n "$written" ]; then disk=$(cat ...
...
if [ -n "$written" ]; then
```
A Write of empty content to an existing SPEC.md truncates the file, which removes the Status. `[ -n "$written" ]` is false, so the comparison is skipped. The same happens when the Edit result is empty, or when an Edit's `old_string` is empty. Command substitution also strips trailing newlines, so edits that only touch them go unseen.

Fix: decide Write versus Edit by whether the `old_string` field is present, not by whether it is non-empty. Compare the statuses unconditionally, treating empty content as status `none`.

3. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:21`** — the status check now runs on specs with no `.task-id`, and the owner check follows it
The `.task-id` early-allow moved below the status guard. That is probably intended, but it also means a spec with a missing or unreadable `.task-id` now hits `hook_fail` on a `cat` error before the owner check runs. Previously such specs were allowed.

Fix: confirm that behavior is intended. Otherwise keep the early allow and run the status check on both paths.