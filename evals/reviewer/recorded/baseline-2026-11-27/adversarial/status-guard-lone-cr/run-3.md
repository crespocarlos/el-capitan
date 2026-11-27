Assessment: request-changes — the guard reads only `tool_input.content`, so Edit and MultiEdit payloads are checked against an empty "after" text, and several paths fail open.

1. [blocking · 4] **`.claude/hooks/lib/spec_guard.py:56`** (h1) — Edit/MultiEdit payloads are evaluated as an empty file
```python
fields = payload.get("tool_input") or {}
print(verdict(fields.get("file_path", ""), fields.get("content", "")))
```
The docstring says this handles Write, Edit and MultiEdit, but only Write carries `content`. Edit carries `old_string`/`new_string` and MultiEdit carries `edits`. For those tools `after` is `""`, so `now` is `""`. Any Edit on a spec that has a Status is then denied with "changes the Status … to 'none'". Any Edit on a spec with no Status passes, so an Edit can still insert a `## Status` section unchecked. I could not see the shell wrapper, so it may pre-compute the post-edit text. Nothing in this file does, though.
Fix: build `after` here by applying `new_string`/`old_string` (with `replace_all`) or each entry in `edits` to `disk`. Alternatively, make the wrapper pass the resulting text and document that contract.

2. [attention · 4] **`.claude/hooks/lib/spec_guard.py:30`** — Import and parse failures fail open
```python
STATUS = canonical_reader()
...
payload = json.loads(sys.stdin.read() or "{}")
```
`canonical_reader()` runs at import time and `json.loads` runs unguarded. If `task_status.py` is moved, has a syntax error, or the payload is malformed, Python exits 1 with a traceback and no stdout. In Claude Code a non-2 exit from a hook is a non-blocking error, so the write proceeds. The wrapper may map empty output to allow. The old awk guard had no such dependency. A refactor of `task_status.py` would silently disable the guard.
Fix: wrap load and parse in `main` and print `deny Task spec guard: cannot evaluate (<error>)`. Alternatively, exit 2 on any exception.

3. [attention · 3] **`.claude/hooks/lib/spec_guard.py:44`** — Creating a new file skips every check
```python
if not os.path.exists(path):
    return f"ok {path}"
```
This early return runs before the duplicate-heading check and the Status comparison. A Write to a new path under the task directory can set any Status, such as `APPROVED`, or contain two `## Status` headings. Whether that is intended depends on how specs are created. If `crew-task.py` is the only legitimate creator, this is a bypass of the guard's purpose. The behavior likely carries over from the awk version.
Fix: run the duplicate-heading check before the existence test. Decide explicitly whether a new file may carry a non-initial Status.

4. [nit · 3] **`.claude/hooks/lib/spec_guard.py:58`** — The one-line protocol breaks if a message contains a newline
`print(verdict(...))` emits `deny … {path}`. A path or Status value containing a newline would split the output, and the wrapper may parse only the first line. The cost is a garbled deny message, which is cosmetic.
Fix: strip newlines from interpolated values.