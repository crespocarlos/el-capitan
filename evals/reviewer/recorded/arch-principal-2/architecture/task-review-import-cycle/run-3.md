Assessment: request-changes — the in-process calls are right, but they make `task` and `review` import each other, and the lazy import in `ls_data.py` only hides that from the load order.

Read beyond the package: `.agent/tools/task/task_bootstrap.py`, `.agent/tools/TOOLS.md`, and a grep for `task_progress`, `review_pr_reads` and `review_records` (the working directory has no `task_progress.py` or `review_pr_reads.py`).

Approach: redirect — replacing the subprocess calls is the right call, but the shared code should live below both packages so neither imports the other.
Alternatives considered:
- Keep the subprocess calls — this is the existing contract and avoids the coupling. It loses because it costs a Python spawn per call and a duplicated "is it already recorded" check, and the diff already shows `crew-metric.py` and `review_records.py` both writing METRIC lines.
- Move the PR-read argv builder and the METRIC append/has helpers into `lib/` (for example `lib/pr_reads.py` and `lib/metrics.py`), and have both packages import from there — this is the better design. It keeps the dependency direction one-way, matches the "never imports back" rule in `TOOLS.md`, and needs no lazy import.
- Keep the diff as it is and document the cross-package edges in `TOOLS.md` — this is the cheapest option. It loses because it puts a `task`→`review` edge in the middle of a chain that `TOOLS.md` describes as one-way.

1. [attention · 4] **`.agent/tools/task/ls_data.py:26`** — the new `task`→`review` import closes a package-level cycle
```python
    from review_pr_reads import add_read_parser, read_argv
```
`review_records` (review) now imports `task_progress` (task) at module level. `ls_data` (task) imports `review_pr_reads` (review) inside the function. The docstring says this keeps the review package from loading for a listing that reads no PR. That does not remove the cycle. If `review_pr_reads` ever imports a module that reaches `review_records`, `crew ls` fails with an ImportError only when it reads a PR. Nothing at load time or in a plain import test would catch that. I could not check `review_pr_reads`'s own imports because the file is not in the package. Neither `review_pr_reads` nor the new edges appear in the `TOOLS.md` dependency order.
Fix: move `add_read_parser` and `read_argv` into `.agent/tools/lib/` (or a task-layer module that `review_pr_reads` re-exports) and import them at the top of `ls_data.py`. Then add the new modules to the `TOOLS.md` chain.

2. [attention · 3] **`.agent/tools/task/ls_data.py:32`** — each PR read builds a parser, and argparse parse errors are swallowed
```python
    except (OSError, subprocess.SubprocessError, SystemExit):
        return 1, ""
```
`ls_data` now keeps a copy of `crew-pr-actions.py`'s parser (the subcommand names `view` and `repo`), so the command list has two owners. If a read gains a required flag, a call site passing the old argv hits `SystemExit`. argparse prints usage to stderr, and `crew ls` shows "PR unavailable" with no cause. Catching `SystemExit` also hides programming errors in the callers' argv.
Fix: have `review_pr_reads` expose a function that takes the command and its arguments and returns the `gh` argv, with no parser. Then drop the `SystemExit` catch.

3. [needs more info · 2] **`.agent/tools/review/review_records.py:11`** — does `has_metric` exist in `task_progress` with the same semantics as the removed check?
```python
from task_progress import append_metric, has_metric
```
The removed code matched the substring `METRIC: review run=<dir> ` in `PROGRESS.md`, tolerating an unreadable file via `errors="replace"`. The new call passes only `review run=<dir> `. If `has_metric` is new or reads the file strictly, a decode error raises from `record_cost` outside the `try`. That would fail a review that had already persisted. Which is it: is `has_metric` unchanged from before, and does it handle a missing or non-UTF-8 `PROGRESS.md`?