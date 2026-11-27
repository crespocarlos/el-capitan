Assessment: comment — the change removes real subprocess coupling, but `task_progress`, `review_pr_reads` and `lib.git` are not in the package, so I can't check the new in-process dependencies for a cycle.

1. [needs more info · 2] **`.agent/tools/review/review_records.py:11`** — new module-level import of `task_progress` makes the review package depend on the task package at load time
```
from task_progress import append_metric, has_metric
```
Before, a broken or missing `task_progress` could only fail the cost line, and the docstring says nothing may fail a review that already persisted. Now an ImportError, or an import cycle if `task_progress` imports anything from `review/`, breaks every review at import. The same applies in reverse: `ls_data` pulls in the review package through `review_pr_reads`. Both bootstraps put all packages on `sys.path`, so resolution works, but I could not read `task_progress.py` or `review_pr_reads.py` to rule out a cycle. Is `task_progress` free of `review_*` imports? If not, a review fails to start. If it is free, consider importing it lazily inside `record_cost` and wrapping that import in the existing try, which keeps the failure isolation the subprocess gave.

2. [needs more info · 2] **`.agent/tools/task/ls_data.py:30`** — `read_pr_actions` re-implements the `crew-pr-actions.py` argument parsing in process
```
for command in ("view", "repo"):
    add_read_parser(commands, command)
...
except (OSError, subprocess.SubprocessError, SystemExit):
```
The `Reader` contract (argv in, `(rc, stdout)` out) is unchanged, so callers are fine. The parser is rebuilt on every call, and `SystemExit` is swallowed, so argparse errors print usage to stderr and then look like a failed read. If `crew-pr-actions.py` adds a pre-processing step that `read_argv` does not cover, `ls` and `crew-pr-actions` will diverge silently. Does `crew-pr-actions.py` use the same `add_read_parser` and `read_argv` for these two commands? If it does not, `ls` output can differ from the CLI. I could not read `lib.git.gh` either, so I don't know whether it raises on a non-zero exit or returns a `CompletedProcess`.