Assessment: request-changes — the guard reads `content`, which only Write payloads carry, so Edit and MultiEdit are mishandled even though the docstring says it handles them.

Read beyond the package: `.agent/tools/task/task_status.py`. `.claude/hooks/lib/` holds only `spec_guard.py`, so I could not read the shell wrapper.

1. [blocking · 4] **`.claude/hooks/lib/spec_guard.py:56`** (h1) — Edit and MultiEdit payloads have no `content`, so `after` is always empty
```python
fields = payload.get("tool_input") or {}
print(verdict(fields.get("file_path", ""), fields.get("content", "")))
```
Edit sends `old_string` and `new_string`, and MultiEdit sends `edits`. Neither sends `content`. An Edit to an existing spec therefore compares the on-disk Status with an empty string. A spec with a Status, such as `DRAFTING`, is denied with "changes the Status … to 'none'", even when the edit touches a different section. The same Edit on a spec with no Status passes, and so would an Edit that sets a Status. Unless the wrapper builds the post-edit text and rewrites the payload (the wrapper is not in the package), the guard blocks legitimate edits and does not stop real status changes.
Fix: for Edit, apply `old_string` → `new_string` to `disk`, honoring `replace_all`. For MultiEdit, apply each entry of `edits` in order. For Write, use `content`. Pass the result to `verdict` as `after`.

2. [attention · 3] **`.claude/hooks/lib/spec_guard.py:43`** — A new file skips every check
```python
if not os.path.exists(path):
    return f"ok {path}"
```
Writing a new spec with `## Status` set to `APPROVED` or `DONE` is allowed. So is a new spec with two `## Status` headings, because the heading check sits below this early return. If creation is meant to go through `crew-task.py`, an agent can skip that path by deleting the file or writing a new one.
Fix: run the duplicate-heading check before the existence check. Also require a new file's Status to be empty or `DRAFTING`, if that is the intended rule.

3. [attention · 3] **`.claude/hooks/lib/spec_guard.py:34`** — Failures to load the reader or parse the payload crash with a traceback
```python
STATUS = canonical_reader()
...
payload = json.loads(sys.stdin.read() or "{}")
```
`canonical_reader()` runs at import time. If `task_status.py` is moved, has a syntax error, or the checkout layout differs, the hook exits non-zero with a traceback and no `deny`/`ok` line. Malformed JSON does the same. The shell wrapper (not in the package) decides whether that fails open or closed. If it ignores the exit code and treats empty output as "allow", the guard is silently off. `open(path)` also raises on a directory or an unreadable file.
Fix: catch these errors in `main`. Print an explicit `deny Task spec guard: cannot evaluate …` so the failure is closed and visible.