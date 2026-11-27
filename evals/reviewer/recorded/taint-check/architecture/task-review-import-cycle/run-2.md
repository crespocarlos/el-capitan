Assessment: request-changes — the change moves a cross-package dependency in process but adds a task→review import that the documented dependency order does not allow, and hides it with a lazy import.

Read beyond the package: `task_bootstrap.py`, `TOOLS.md`. `task_progress`, `review_pr_reads`, `lib/git` and `crew-metric.py` are not in the working directory, so I could not read them.

1. [attention · 3] **`.agent/tools/task/ls_data.py:26`** — task package now imports into review, against the documented dependency order
```python
    from review_pr_reads import add_read_parser, read_argv
```
`TOOLS.md` orders the task chain as `task_status` → `task_progress` → `task_state` → `ls_data` → `task_report`, and review as a separate chain. `review_records` now imports `task_progress`, and `ls_data` imports `review_pr_reads`, so the two packages depend on each other. The function-level import is what keeps this from failing at load time. If `review_pr_reads` or anything it imports ever reaches `task_state` or `ls_data`, `crew ls` breaks with an import-order failure that only shows up on the first PR read. The docstring's reason ("a listing that reads no PR never loads it") describes the cost saving, not the cycle.
Fix: move the PR read helpers (`add_read_parser`, `read_argv`) into a neutral module, for example under `lib/`, that both `crew-pr-actions.py` and `ls_data` import. Then update the dependency chain in `TOOLS.md`.

2. [attention · 3] **`.agent/tools/task/ls_data.py:33`** — the read's argv is built by round-tripping through an argparse parser that is a copy of the CLI's
```python
    for command in ("view", "repo"):
        add_read_parser(commands, command)
    ...
    except (OSError, subprocess.SubprocessError, SystemExit):
```
A new parser is built on every read, and it has to stay in step with the subcommand set that `crew-pr-actions.py` registers. If `add_read_parser` gains a required flag, `parse_args` calls `SystemExit`. That is swallowed as `(1, "")`, so every PR reads as not landed, with no message. Argparse also prints usage to stderr first. The `ImportError` from the lazy import is outside the `try`, so it propagates and fails the whole listing.
Fix: expose a function in the shared module that takes plain arguments (`view(ref)`, `repo()`) and returns the argv. Have `ls_data` call it without argparse, and keep SystemExit out of the error path.

3. [attention · 3] **`.agent/tools/review/review_records.py:11`** — the duplicate-check and the append are now two separate steps in the caller, and the "one writer" guarantee depends on `append_metric` alone
```python
    if has_metric(owner, f"review run={review_dir.name} "):
        return payload
    try:
        append_metric(owner, payload)
```
The check and the append were already separate before this change. The check-then-append sequence is not atomic, so two concurrent persists for the same review run can both pass `has_metric` and write the METRIC line twice. The docstring also claims `crew-metric.py` "calls it too", which I could not verify because that file is not present. If it does not, there are two writers again. Also, the old non-zero-exit warning is gone, and a failure type other than `OSError` or `ValueError` from `append_metric` now propagates out of a step the docstring says must never fail a persisted review.
Fix: put the dedupe inside `append_metric`, for example with an `unless_present` key argument, and have `record_cost` catch `Exception` for the swallow.