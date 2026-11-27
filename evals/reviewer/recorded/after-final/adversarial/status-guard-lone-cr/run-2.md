Assessment: request-changes — the guard reads only `content`, so Edit and MultiEdit payloads, which the docstring says it handles, are judged against an empty "after" text.

Read beyond the package: `.agent/tools/task/task_status.py`. The calling shell script `check-task-spec-owner.sh` is not in the working directory, so I could not check what it passes to this script.

1. [attention · 3] **`.claude/hooks/lib/spec_guard.py:56`** — Edit and MultiEdit payloads are evaluated with `after=""`
```python
fields = payload.get("tool_input") or {}
print(verdict(fields.get("file_path", ""), fields.get("content", "")))
```
The docstring says the script takes a Write, Edit or MultiEdit payload. Only Write carries `content`. Edit carries `old_string` and `new_string`, and MultiEdit carries `edits`. For those tools `after` is `""`, so `status(after)` is `""`. If the shell wrapper has not already applied the edit, any Edit to a spec with a Status is denied with "changes the Status … to 'none'". Edits to a spec with no Status pass with no check. A real Status edit is not caught either, because the new text is never examined. Fix: apply `old_string`/`new_string` (and each MultiEdit entry, honouring `replace_all`) to `disk` to build `after`. If the wrapper already does this, rename the field and document it.

2. [attention · 3] **`.claude/hooks/lib/spec_guard.py:44`** — an unreadable file or a load failure crashes with a traceback and no verdict
```python
with open(path, encoding="utf-8", newline="") as handle:
    disk = handle.read()
```
A spec that is not valid UTF-8, or one with a permission error, raises an uncaught `UnicodeDecodeError` or `OSError`. `STATUS = canonical_reader()` also runs at import time, so a missing or broken `task_status.py` crashes every invocation. The script then exits non-zero with empty stdout. What that does depends on the wrapper: it may fail open and silently disable the guard, or fail closed and block every spec write. Neither outcome is deliberate. Fix: catch these errors in `main` and print an explicit `deny` (or `skip`) with the reason.

3. [nit · 3] **`.claude/hooks/lib/spec_guard.py:46`** — the duplicate-heading check runs before the Status comparison and also counts headings inside code fences
A spec that already has two `## Status` headings, or that quotes one in a fenced example, has every later write refused, even an unrelated one. The refusal message does not say whether the write added the duplicate or it was already there. The cost is that the author cannot tell why the write was refused. Fix: refuse only when `len(HEADING.findall(after)) > len(HEADING.findall(disk))`, or say in the message that the duplicate was already present.