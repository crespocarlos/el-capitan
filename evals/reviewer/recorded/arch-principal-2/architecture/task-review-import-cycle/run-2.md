Assessment: request-changes — the in-process calls create a task↔review package cycle, and the lazy import in `ls_data.py` hides it. I could only read three of the touched files, so I could not confirm that.

Read beyond the package: `task_bootstrap.py`, `TOOLS.md`. `task_progress.py` and `review_pr_reads.py` are not in the working directory, so I read neither.

Approach: redirect — in-process calls are the right goal, but the shared pieces belong in a lower layer that neither package has to reach up into.
Alternatives considered:
- Keep the subprocess calls — this loses on coupling and cost. It does keep the layering intact, and it leaves the package cycle unbuilt. I would keep it as a fallback if the move below is too big.
- Move `append_metric`/`has_metric` and the PR read helpers (`review_pr_reads`) into `.agent/tools/lib`, which both packages already import (`lib.git`). This wins. Each package then depends only on `lib`, `ls_data` needs no function-level import, and the documented order in `TOOLS.md` stays true.
- Keep the direct imports as written and document them. This is the cheapest option, but it makes `task` and `review` depend on each other. That is only safe if `review_pr_reads` never imports back into `task`, which I could not check.

1. [attention · 3] **`.agent/tools/task/ls_data.py:26`** — task layer lazily imports the review package, while review already imports task
```
    from review_pr_reads import add_read_parser, read_argv
```
`review_records` (review) now imports `task_progress` (task), and `ls_data` (task) imports `review_pr_reads` (review) inside the function. `TOOLS.md` promises that "a module never imports back into one that imports it", and it lists no cross-package order. If `review_pr_reads` or its imports ever reach `review_records`, `review_report` or any other module that pulls in `task_progress`, `crew ls` fails with an ImportError only when it reads a PR. The function-level import hides the cycle at load time, so lint and the import-order tests will not catch it. The docstring justifies the lazy import as saving load time, which is not the real reason it has to be lazy.
Fix: move the shared read helpers (`add_read_parser`, `read_argv`) and the metric helpers into `lib`, or into a module with no upward imports. Then import them at the top of each file. If the cross-package dependency stays, add it to the order in `TOOLS.md`.

2. [attention · 3] **`.agent/tools/task/ls_data.py:30`** — an argparse failure is swallowed and also prints to stderr
```
        args = parser.parse_args(arguments)
        ...
    except (OSError, subprocess.SubprocessError, SystemExit):
        return 1, ""
```
Catching `SystemExit` hides a real bug, such as a caller passing an argv that `view` or `repo` does not accept. argparse also writes a usage error to stderr first, because `add_help=False` does not silence errors. `crew ls` then shows stray usage text and treats the PR as unreadable, where the old subprocess call returned quietly. The `gh` timeout is also now raised from the `lib.git` helper. If that helper raises something other than `OSError` or `SubprocessError` (for example its own error type), the exception escapes `crew ls` instead of returning `(1, "")`.
Fix: build the argv directly with `read_argv`, or expose a pure function that does not go through argparse. If argparse stays, use `exit_on_error=False`, catch `argparse.ArgumentError`, and check which exceptions `gh()` raises.

3. [needs more info · 2] **`.agent/tools/review/review_records.py:11`** — `has_metric` is new, and the dedupe check changed hands
```
from task_progress import append_metric, has_metric
...
    if has_metric(owner, f"review run={review_dir.name} "):
```
The old inline check read `PROGRESS.md` with `errors="replace"` and matched `METRIC: review run=<name> `. I could not see whether `has_metric` keeps that exact matching. If it does not, for example because it reads strictly or needs a different prefix, a rerun of a review could append a second cost line, or `UnicodeDecodeError` could escape the `except (OSError, ValueError)` handler. `UnicodeDecodeError` is a `ValueError`, so that case is caught. The risk is the changed matching, which would double-count cost. Question: does `has_metric` match `METRIC: review run=…` and tolerate undecodable bytes, and does `append_metric` do the same validation and locking as `crew-metric.py`?