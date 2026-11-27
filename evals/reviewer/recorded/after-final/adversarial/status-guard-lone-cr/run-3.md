Assessment: request-changes — the guard compares the Status of the disk file against `tool_input.content`, which only a Write payload carries, so Edit and MultiEdit are not handled despite the docstring.

Read beyond the package: `.agent/tools/task/task_status.py`. The `check-task-spec-owner.sh` wrapper is not in the working directory, so I could not check how it calls this script or what it does when the script fails.

1. [attention · 4] **`.claude/hooks/lib/spec_guard.py:56`** — Edit and MultiEdit payloads are read as if they were Write payloads
```
fields = payload.get("tool_input") or {}
print(verdict(fields.get("file_path", ""), fields.get("content", "")))
```
The docstring says it handles "one Write, Edit or MultiEdit payload". Edit sends `old_string`/`new_string` and MultiEdit sends `edits`, so neither has `content`, and `after` becomes `""`. An Edit that touches only the Summary of a spec with a Status then gives `status(after) == ""`. That differs from the on-disk status, so the guard denies the edit with "changes the Status … to 'none'". An Edit that does rewrite the Status is judged the same way, against an empty string, so it is not checked as a real change. Fix: apply the edits to `disk` to build `after` (or have the wrapper pass the resulting text), then compare. If the wrapper already does this, rename the field or document it.

2. [attention · 3] **`.claude/hooks/lib/spec_guard.py:42`** — A new file skips both the Status check and the duplicate-heading check
```
if not os.path.exists(path):
    return f"ok {path}"
```
A Write that creates a spec with `## Status\nDONE` or `APPROVED`, or one with two Status headings, returns ok. The agent can then start a spec at any state without going through `crew-task.py`. The existence check also runs before the duplicate-heading check, so the heading rule is skipped for new files. Fix: run the duplicate-heading check before the existence check, and decide whether a new file's Status must be empty or `DRAFTING`.

3. [attention · 3] **`.claude/hooks/lib/spec_guard.py:20`** — `resolve()` may point at the wrong checkout when the hook is symlinked
```
source = Path(__file__).resolve().parents[3] / ".agent" / ...
```
The docstring says the module is loaded from "the checkout this hook links into". `resolve()` follows symlinks to the real file, so a symlinked hook computes its root from the link target, not from the checkout it was linked into. Either the canonical reader is not found, or the reader comes from a different checkout than the one being guarded. The failure happens at import time. Fix: use `Path(__file__).absolute()` (no symlink resolution), or take the root from `CLAUDE_PROJECT_DIR` or the git toplevel.

4. [needs more info · 3] **`.claude/hooks/lib/spec_guard.py:55`** — Unhandled exceptions end in a traceback, and the result depends on the wrapper
`json.loads`, a non-UTF-8 file on disk (`UnicodeDecodeError`), an unreadable file, or an import failure in `canonical_reader()` all raise and exit nonzero with no `deny` or `skip` line. If the wrapper treats empty output or a nonzero exit as allow, a corrupt or undecodable spec or a broken `task_status.py` turns the Status guard off silently. If it treats them as deny, every write to specs is blocked. Which behaviour does `check-task-spec-owner.sh` implement? Whichever it is, the script should print an explicit `deny` or `skip`.