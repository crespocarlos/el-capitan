Assessment: request-changes — the hook's awk parser doesn't match `task_status.STATUS`, so an Edit or Write can change the status that `read_status` returns without the guard seeing it.

1. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:27`** — the awk status parser disagrees with `read_status` when a second `## Status` section exists
```
awk '/^## Status[ \t]*$/ { f = 1; next } f && /^#/ { exit } f && NF { ...print; exit }'
```
The awk takes the first non-blank line under the first `## Status` header. `task_status.STATUS` is `^(## Status[ \t]*\r?\n)([^\n#][^\n]*?)[ \t]*$`, so the value must be on the line immediately after the header. If the first header is followed by a blank line or by a `#` line, the Python regex skips it and matches a later `## Status` section.

Concrete bypass: take a spec where the first `## Status` is followed by a blank line. Append `## Status\nDONE` with an Edit or Write. The awk still reports the first section's first non-blank line, so before equals after and the guard allows it. `read_status` now returns DONE, so Gate 1 is bypassed by the very route this change closes. The same mismatch works in reverse, as a false deny.

The comment in `task_status.py` says hooks must not re-implement the reader. This hook does anyway, and it diverges.

Fix: don't re-implement the parser. Have the hook write `disk` and `written` to temp files and call `task_status.read_status` on both, or call a small Python entry point that applies `STATUS.search`. Compare the two results. If you must keep awk, require the value on the line immediately after the header and take the first matching header the way `search` does.

2. [attention · 4] **`.claude/hooks/check-task-spec-owner.sh:27,39`** — CRLF headers and empty Writes skip the guard
```
/^## Status[ \t]*$/ ...
if [ -n "$written" ]; then
```
With CRLF line endings, the awk header pattern never matches because of the trailing `\r`, which the Python regex tolerates. Both `before` and `after` come out empty, so any status change passes. Separately, a Write with empty `content` sets `written=""` and skips the whole comparison. That lets a Write truncate the spec and wipe the Status without being denied, and `read_status` then returns "" afterward.

Fix: strip `\r` before parsing, for example `tr -d '\r'`, or let `read_status` do the parsing as in finding 1. Run the comparison whenever the tool is Write, even when the content is empty. Treat a missing or changed status as a change.