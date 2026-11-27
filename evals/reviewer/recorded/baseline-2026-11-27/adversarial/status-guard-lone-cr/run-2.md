Assessment: request-changes — the guard only reads `content`, so Edit and MultiEdit payloads are checked against an empty document instead of the post-edit text.

1. [blocking · 4] **`.claude/hooks/lib/spec_guard.py:58`** (h1) — Edit/MultiEdit payloads are evaluated as an empty file
```python
fields = payload.get("tool_input") or {}
print(verdict(fields.get("file_path", ""), fields.get("content", "")))
```
The docstring says this handles Write, Edit and MultiEdit. Only Write carries `content`. Edit sends `old_string` and `new_string`. MultiEdit sends `edits`. For those tools `after` is `""`, so `status(after)` is `""`. This has two effects:
- Any Edit on a spec that has a Status value is denied with "changes the Status … to 'none'", even when the edit only touches the body.
- On a spec with no Status, every Edit is allowed, including one that adds a Status. The duplicate-heading check never sees real text.

The guard then both blocks legitimate edits and misses the status changes it exists to stop. I could not see `check-task-spec-owner.sh`. If it reconstructs the post-edit content before calling this script, the payload shape differs from what this code reads, and that should be stated.

Fix: apply `old_string`/`new_string` (and each entry of `edits` in order, honouring `replace_all`) to `disk` to build `after`. Fall back to `content` only for Write.

2. [attention · 3] **`.claude/hooks/lib/spec_guard.py:47`** (h1) — Unhandled exceptions give no verdict, and the shell wrapper's reaction is unknown
```python
with open(path, encoding="utf-8", newline="") as handle:
    disk = handle.read()
...
payload = json.loads(sys.stdin.read() or "{}")
```
These can raise and exit with a traceback instead of printing `skip`, `ok` or `deny`:
- the module-level `canonical_reader()` (missing or broken `task_status.py`)
- `UnicodeDecodeError` on a non-UTF-8 spec
- `PermissionError` or `IsADirectoryError` from `open`
- malformed JSON on stdin

If the wrapper treats empty output as allow, the guard fails open on any of these. If it treats it as deny, a broken `task_status.py` locks every spec write. The old awk version had neither failure mode.

Fix: wrap `main` and `verdict`. Choose one behaviour deliberately, most likely `deny` with the error text, and print it in the expected format.

3. [attention · 3] **`.claude/hooks/lib/spec_guard.py:46`** (h1) — The duplicate-heading refusal also blocks a spec that already has two headings
```python
if len(HEADING.findall(after)) > 1:
    return "deny … more than one '## Status' heading …"
```
This runs before the before/after comparison. A spec that already has two headings can only be edited by a write that fixes the duplication. Unrelated edits are refused, and the message doesn't say the duplicate was already there. `HEADING` is also a second, separate definition of the heading, which the `STATUS` comment says hooks must not do. It counts headings inside fenced code blocks, and `STATUS` does not distinguish them either. A spec that quotes the template in a code fence would be refused.

Fix: refuse only when the count of headings in `after` is greater than the count in `disk`, or greater than 1 while the count in `disk` is 1 or fewer. Count the headings with the same canonical definition.

4. [nit · 2] **`.claude/hooks/lib/spec_guard.py:42`** — A new file skips every check
```python
if not os.path.exists(path):
    return f"ok {path}"
```
Creating a spec with `Status: DONE` is allowed, as is creating one with duplicate headings. This is probably deliberate for new specs, since they need an initial state. The duplicate-heading check could still run on the new content. The cost of leaving it is a spec created already in an arbitrary state.