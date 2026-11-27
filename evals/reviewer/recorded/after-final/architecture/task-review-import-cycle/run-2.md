Assessment: request-changes — the change adds a task↔review package dependency in both directions, and the documented module order has no place for either edge.

Read beyond the package: `.agent/tools/task/task_bootstrap.py`, `.agent/tools/TOOLS.md`. `review_pr_reads.py` and `task_progress.py` are not in the working directory, so I could not read them.

1. [attention · 3] **`.agent/tools/task/ls_data.py:26`** — a lazy import hides a task↔review package cycle
```python
    from review_pr_reads import add_read_parser, read_argv
```
```python
from task_progress import append_metric, has_metric
```
`TOOLS.md` orders modules as `task_progress` → … → `ls_data` and `review_vocabulary` → … → `review_report`. It says "a module never imports back into one that imports it". After this change `review_records` (review) imports `task_progress` (task), and `ls_data` (task) imports `review_pr_reads` (review). Neither edge is in the documented order. The function-level import in `ls_data` keeps the cycle from failing at load time. It is also why a future `review_pr_reads` → `task_*` import, or a `task_progress` → `review_*` import, would only fail at runtime, and only when `crew ls` reads a PR. I could not read `review_pr_reads.py` or `task_progress.py` to rule that out.
Fix: Put the shared pieces in a layer that neither package owns, such as `lib/` for the PR read argv/parser and the METRIC writer. Otherwise, add both edges to the `TOOLS.md` order and add a test that imports every module in a fresh interpreter.

2. [attention · 3] **`.agent/tools/task/ls_data.py:34`** — `crew ls` now depends on a reader's private parser internals
```python
    for command in ("view", "repo"):
        add_read_parser(commands, command)
    ...
    except (OSError, subprocess.SubprocessError, SystemExit):
```
The old contract was a CLI: argv in, exit code and stdout out. The new one is `add_read_parser` and `read_argv`, which are argparse-internal helpers. If a flag is renamed or made required in `review_pr_reads`, argparse calls `SystemExit`, and the `except` turns that into `(1, "")`. `crew ls` then shows every PR as unreadable and nothing reports why. Argparse also prints its usage error to stderr, which corrupts `crew ls` output.
Fix: Expose a plain function in `review_pr_reads`, such as `read_pr(kind, **fields) -> CompletedProcess`. Call it from `ls_data`, and drop the argparse round-trip and the `SystemExit` catch.

3. [nit · 3] **`.agent/tools/review/review_records.py:26`** — the idempotence check and the write are now two separate calls
```python
    if has_metric(owner, f"review run={review_dir.name} "):
        return payload
    try:
        append_metric(owner, payload)
```
Previously the dedupe string was built in `review_records` and the write happened in another process. Now `has_metric` and `append_metric` both live in `task_progress`, but the caller still builds the `"review run=… "` prefix. The `METRIC:` line format is therefore known to two modules. Concurrent reviews on one task could also both pass the check and write twice.
Fix: Add `append_metric_once(owner, key_prefix, payload)` in `task_progress`, so one module owns both the format and the check.