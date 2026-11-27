Assessment: request-changes — the change removes the subprocess seam but leaves a task→review import beside the existing review→task one, and I couldn't confirm the new helpers exist.

Read beyond the package: `task_bootstrap.py`, `TOOLS.md`. A glob for `task_progress*`, `review_pr_reads*`, `crew-metric*` and `crew-pr-actions*` found none of them in the working directory, so the helpers' contents are unverified.

1. [blocking · 3] **`.agent/tools/task/ls_data.py:26`** — task package now imports the review package, while review already imports task

```
from review_pr_reads import add_read_parser, read_argv
...
# review_records.py
from task_progress import append_metric, has_metric
```

`TOOLS.md` fixes one dependency order per package, and the stated rule is that a module never imports back into one that imports it. `ls_data` is in the task chain (`task_progress` → `task_state` → `ls_data`). It now reaches into `review_pr_reads`, and `review_records` reaches back into `task_progress`. The function-local import hides the package cycle from load time and from any import-order lint. If `review_pr_reads` or its imports ever pull in `review_records`, `review_report` or any `task_*` module, `crew ls` raises ImportError on first PR read. Nothing in this code path catches that error, because the `except` only wraps the parse and `gh` call. I couldn't read `review_pr_reads`, so I can't rule that out. `TOOLS.md` also doesn't place `review_pr_reads` in the dependency order.
Fix: move `add_read_parser` and `read_argv` into a leaf module that depends only on `lib`, for example `lib/pr_reads.py`. Have both packages import that module, remove the lazy import, and add the module to the `TOOLS.md` order.

2. [attention · 3] **`.agent/tools/task/ls_data.py:32`** — `SystemExit` is swallowed and the failure reason is lost

```
except (OSError, subprocess.SubprocessError, SystemExit):
    return 1, ""
```

The old code returned the child's exit status and stdout. A bad argv (a parser mismatch between `ls_data` and `add_read_parser`) now prints argparse usage to stderr in the middle of `crew ls` output. It then reads as "PR unavailable", the same result as no `gh` installed. A contract drift between the two modules would show up as quietly missing PR columns. Rebuilding the parser on every call also duplicates the `view` and `repo` subcommand list, which the review package owns.
Fix: have `review_pr_reads` expose a function that takes the command name and its arguments and builds argv without argparse, and drop the `SystemExit` catch. Otherwise, build the parser once, with `exit_on_error=False`.

3. [attention · 3] **`.agent/tools/review/review_records.py:11`** — `ValueError` assumed as the rejection signal, and the cost writer now fails at import time

```
from task_progress import append_metric, has_metric
...
except (OSError, ValueError) as error:
```

`crew-metric.py` used to be the validation boundary, and any non-zero exit was swallowed. The new `except` covers only `OSError` and `ValueError`. If `append_metric` rejects a payload another way, such as through `SystemExit` or a custom error, the exception escapes after the review has already persisted. This breaks the "nothing here may fail a review" guarantee. The module-level import also means a break in the task package now stops every review import, where before only the metric write could fail.
Fix: confirm which exceptions `append_metric` raises. Catch `Exception` at this boundary, and keep the `has_metric` call and the import inside the guarded path if the review must stay independent of the task package.