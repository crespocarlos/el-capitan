Assessment: comment — the change removes real subprocess coupling, but I couldn't read `task_progress` or `review_pr_reads`, so I couldn't rule out an import cycle or a changed contract.

Read beyond the package: `.agent/tools/task/task_bootstrap.py`, `.agent/tools/TOOLS.md`. A glob for `task_progress`, `review_pr_reads`, `crew-metric` and `crew-pr-actions` found no files in the working directory.

1. [needs more info · 2] **`.agent/tools/task/ls_data.py:26`** — a task-to-review import sits inside the task dependency chain
```
    from review_pr_reads import add_read_parser, read_argv
```
`TOOLS.md` lists `task_progress → task_state → … ls_data` and `review_vocabulary → … → review_report` as two separate chains. Two edges now cross between them. `ls_data` (task) lazily imports `review_pr_reads` (review). `review_records` (review) imports `task_progress` (task). The lazy import hides a possible cycle: if `review_pr_reads` or any module it imports reaches `task_*`, `crew ls` gets a task→review→task loop. That loop only fails at call time, when a listing reads a PR. Does `review_pr_reads` import anything from the task package or from `review_records`? If it does, `crew ls` on a PR-bearing task raises ImportError. The surrounding `try` doesn't cover the import, so it would crash instead of returning `(1, "")`.

2. [attention · 3] **`.agent/tools/TOOLS.md:6`** — the documented dependency order doesn't show the new cross-package edges
```
`task_status` → `task_progress` → `task_state` → `task_resolve`/`task_gates`/`ls_data` → `task_report`
```
This is the documented rule that "a module never imports back into one that imports it". The diff adds `review_records → task_progress` and `ls_data → review_pr_reads` (lazy). Neither is recorded. A later contributor who makes `task_progress` import a review module will create a cycle, and the doc gives no warning.
Fix: add the two cross-package edges to the dependency-order paragraph. Also say that `review_pr_reads` must not import `task_*`.

3. [attention · 3] **`.agent/tools/task/ls_data.py:30`** — the in-process read now rebuilds the parser, and bad argv is swallowed as a failed read
```
        args = parser.parse_args(arguments)
        done = gh(*read_argv(args.command, args), timeout=45)
    except (OSError, subprocess.SubprocessError, SystemExit):
```
The parser is rebuilt on every read, so the read argv contract is now duplicated as the `view` and `repo` command names. If `crew-pr-actions.py` renames a flag, `ls_data` stops matching it. `parse_args` then raises `SystemExit`, which is caught, so every PR shows as an unreadable `(1, "")` and `crew ls` stays silent about the cause. The `SystemExit` handler also lets argparse print usage to stderr in the middle of a listing.
Fix: have `review_pr_reads` expose a function that takes `(command, fields)` and returns the argv. Then `ls_data` skips argparse, and a signature mismatch fails loudly.

4. [nit · 2] **`.agent/tools/review/review_records.py:29`** — the swallowed exceptions are narrower than the old ones
```
    except (OSError, ValueError) as error:
```
The old code swallowed every `SubprocessError` and any non-zero exit. Now an unexpected exception type from `append_metric` (for example a `UnicodeDecodeError`, which is a `ValueError` and so caught, or a lock timeout) would fail a review that had already persisted. The docstring says nothing here may do that. The cost is that a review which already persisted can still crash at its last step.