Assessment: request-changes — the change turns two subprocess boundaries into imports, and `task` and `review` now import each other. The documented dependency order doesn't cover that, and I couldn't read the new APIs the change relies on.

Read beyond the package: `.agent/tools/task/task_bootstrap.py`, `.agent/tools/TOOLS.md`, and a grep for `review_pr_reads` and `task_progress` (the only source files in the tree are `ls_data.py`, `review_records.py` and `task_bootstrap.py`).

Approach: redirect — in-process calls are the right direction, but the `task` and `review` packages now depend on each other, so put the shared pieces in a layer both import.
Alternatives considered:
- Keep the subprocess calls — this is the status quo. It is slower and its errors are stringly typed, but it has no coupling. It loses on cost, but it is the only design that does not create the package cycle.
- Move `review_pr_reads` (the gh read builders) and `append_metric` and `has_metric` into `lib/`, or into a leaf module below both packages — this wins. `task` and `review` would each import downward only. It also removes the lazy-import workaround and the argparse round trip.
- Have `crew-ls` take a callable reader through its existing `Reader` seam, with the `review` package supplying it at the entry point — this is a viable second option. `ls_data` stays free of `review` imports, and the seam already exists.

Next changes and what they cost under this design:
- Adding another PR read command means editing `ls_data`'s hardcoded `("view", "repo")` tuple and the `review` parser together.
- Changing the `append_metric` signature touches `review_records`, `crew-metric.py` and any other caller.
- Adding a third package that needs the task or review internals repeats the same cross-package edge.

1. [attention · 4] **`.agent/tools/task/ls_data.py:26`** — `task` now imports `review` lazily, while `review_records` imports `task_progress`, so the packages form a cycle
```
    from review_pr_reads import add_read_parser, read_argv
...
from task_progress import append_metric, has_metric
```
`review_records` (review) imports `task_progress`, and `ls_data` (task) imports `review_pr_reads`. `TOOLS.md` says "a module never imports back into one that imports it" and gives the order `task_progress` → `task_state` → `ls_data`. The order lists no edge from `ls_data` into `review`, so the cycle is hidden only because the import is function-local. If `review_pr_reads`, or anything it imports, ever imports `review_records` or a `task_*` module above `task_progress`, `crew ls` hits a circular import the first time it reads a PR. Nothing at load time or in a test of an empty listing would catch it. The lazy import also needs `task_bootstrap` to have put the `review` directory on `sys.path`, which `PACKAGES` does today.
Fix: move the PR read builders (`add_read_parser`, `read_argv`) into a module below both packages, such as `lib/pr_reads.py`, and import it at the top of `ls_data`. Otherwise record the `review` → `task` and `task` → `review` edge in `TOOLS.md`, and add a test that imports each module in a fresh interpreter.

2. [attention · 3] **`.agent/tools/task/ls_data.py:30`** — building an argparse parser to turn argv into a `gh` call, and swallowing `SystemExit`, hides bad input
```
        args = parser.parse_args(arguments)
        done = gh(*read_argv(args.command, args), timeout=45)
    except (OSError, subprocess.SubprocessError, SystemExit):
        return 1, ""
```
A malformed argv, such as a flag one side renamed, makes argparse print usage to stderr and raise `SystemExit`. That is now reported as a failed read, so the PR column silently goes blank instead of surfacing the programming error. The parser is also rebuilt on every call, which is once per PR in a listing. Only `view` and `repo` are registered, so a new read command fails the same quiet way.
Fix: have `review_pr_reads` expose a function that takes structured arguments and returns the `gh` argv. `ls_data` would call it directly with no parser, and a bad call would raise a normal exception.

3. [needs more info] **`.agent/tools/review/review_records.py:11`** — the new APIs and the old scripts' behaviour could not be checked
`review_pr_reads`, `task_progress.append_metric`, `task_progress.has_metric` and `lib.git.gh` are not in the package. Three things depend on them:
- **Equivalence:** the old subprocess path ran `crew-pr-actions.py` and `crew-metric.py` with their own argument validation, cwd and env handling. If either script did more than the new functions do (payload validation, a file lock, repo resolution), that behaviour is now skipped on the in-process path.
- **Exceptions:** the `except (OSError, ValueError)` clause only holds if `append_metric` raises nothing else, such as a `SystemExit` for a bad payload.
- **Duplicate check:** `has_metric` replaces the old inline substring test, and a mismatch would let a rerun append a second cost line.

Question: do `crew-metric.py` and `crew-pr-actions.py` route through the same functions the new code calls, and does `append_metric` raise only `OSError` or `ValueError`? If not, a bad payload can crash an already persisted review, or a validation step is lost. Please also confirm that the package's tests exercise the new `has_metric` and `append_metric` calls.