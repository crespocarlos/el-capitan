Assessment: request-changes — the guard only reads `content`, so Edit and MultiEdit payloads are judged against an empty string, and any load failure leaves the hook without a verdict.

1. [blocking · 4] **`.claude/hooks/lib/spec_guard.py:56`** — Edit and MultiEdit payloads are evaluated as an empty file
```python
fields = payload.get("tool_input") or {}
print(verdict(fields.get("file_path", ""), fields.get("content", "")))
```
The docstring says this handles Write, Edit or MultiEdit, but only Write carries `content`. Edit sends `old_string` and `new_string`. MultiEdit sends `edits`. For those tools `after` is `""`, so `status(after)` is `""`. Any Edit to an existing spec that has a Status is then denied as "changes the Status … to 'none'", including edits that never touch the Status. If the shell wrapper reconstructs the post-edit text, that code is not in the package (the only hook file present is `spec_guard.py`), so I could not confirm it. A wrapper that does not reconstruct it is both a false-deny on every body edit and a way to evade the check.
Fix: apply the edit(s) to `disk` inside Python to build `after`. Replace the first match of `old_string`, or all matches when `replace_all` is set. For MultiEdit, apply `edits` in order. Then run the same checks on the result.

2. [attention · 3] **`.claude/hooks/lib/spec_guard.py:30`** — Loading the reader at import time can fail with no verdict
```python
STATUS = canonical_reader()
```
If `task_status.py` is missing, moved, or has a syntax error, or if the stdin JSON is malformed (`json.loads` in `main`), the script exits with a traceback and prints no `skip`/`ok`/`deny`. The wrapper is not in the package, so I could not check what it does with empty output. If it treats that as allow, the guard fails open exactly when the canonical reader breaks.
Fix: catch exceptions in `main`, including around the import, and print an explicit `deny Task spec guard: cannot evaluate …`. Confirm the wrapper treats missing output as deny.

3. [nit · 2] **`.claude/hooks/lib/spec_guard.py:25`** — `HEADING` counts `## Status` lines inside fenced code blocks
A spec that quotes a `## Status` template in a code fence is refused as having duplicate headings. Because `STATUS` is also line-based, that fenced line could be read as the real Status, so refusing is arguably correct. The cost is a false deny with a confusing message.