Assessment: comment — I couldn't read `task_progress.py` or `review_pr_reads.py` (neither is in the working directory), so I couldn't confirm the new in-process calls have the signatures the diff assumes. The direction of the change is sound.

1. [needs more info · 3] **`.agent/tools/task/ls_data.py:26`** (h1) — a lazy import from `task` into `review` hides a package cycle
```python
    from review_pr_reads import add_read_parser, read_argv
```
`TOOLS.md` documents the dependency order `task_status → task_progress → task_state → … → ls_data`, and says "a module never imports back into one that imports it". This diff adds `review_records` (review) → `task_progress` (task) and `ls_data` (task) → `review_pr_reads` (review). That is a cross-package cycle, and the function-local import (with the docstring's "never loads it" rationale) is what keeps it from failing at load time. Is the cycle intentional? If `review_pr_reads` or anything it imports ever reaches `review_records`, `task_progress`, or `ls_data`, `crew ls` will fail with an ImportError on its first PR read. The failure would appear only at call time and could be swallowed by callers. `TOOLS.md` doesn't mention either new edge. I couldn't read `review_pr_reads`'s imports to rule this out. If the cycle is unintended, the fix is to move the shared read helpers (`add_read_parser`, `read_argv`) and `gh` down into a neutral module such as `lib`. Otherwise, document the edges in `TOOLS.md`.

2. [attention · 3] **`.agent/tools/task/ls_data.py:30`** (h1) — the `SystemExit` catch treats a parser rejection as a failed PR read
```python
    except (OSError, subprocess.SubprocessError, SystemExit):
        return 1, ""
```
`parser.parse_args` calls `sys.exit(2)` on bad argv and writes usage text to stderr. Catching `SystemExit` hides a programming error (argv built by `ls_data` that the parser rejects) as an ordinary "read failed". That is also what `crew ls` shows for a missing `gh`. The parser is rebuilt on every call, and `argparse` is now a dependency of a data module. `ls_data` already builds the argv itself, so it could call `read_argv` directly and skip the parse. If that isn't possible, give the parser `exit_on_error=False` and catch `argparse.ArgumentError`, so only genuine runtime failures are swallowed.
Fix: build the `read_argv` input without the round-trip through `argparse`, or stop catching `SystemExit`.

3. [attention · 3] **`.agent/tools/review/review_records.py:28`** (h2) — the error contract of the replacement call is narrower than the old subprocess path
```python
    try:
        append_metric(owner, payload)
    except (OSError, ValueError) as error:
```
The docstring says "Nothing here may fail a review that already persisted". The subprocess boundary used to guarantee that, because any crash in `crew-metric.py` became a non-zero exit. Now any other exception from `append_metric` (for example a `UnicodeError` that isn't a `ValueError` subclass, or a lock or `KeyError` problem inside `task_progress`) will propagate out of `record_cost` and fail a persisted review. Catching only `OSError` and `ValueError` relies on `append_metric` documenting exactly those two. I couldn't verify that.
Fix: confirm that `append_metric` raises only `OSError` or `ValueError`. Otherwise catch `Exception` at this best-effort boundary.

4. [nit · 2] **`.agent/tools/review/review_records.py:11`** (h2) — the duplicate-metric check is now separate from the write
`has_metric` followed by `append_metric` is a check-then-act pair across two calls. The old code was the same, so this change doesn't make it worse. Two concurrent reviews with the same run name could still both write. Moving the dedupe inside `append_metric` would remove the race, and it would mean `crew-metric.py` gets the same protection.