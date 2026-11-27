Assessment: request-changes — the change replaces subprocess calls with in-process imports that cross the task and review packages in both directions, and the documented dependency order has no place for those edges.

Read beyond the package: `task_bootstrap.py`, `TOOLS.md`. `task_progress`, `review_pr_reads` and `lib/git` are not in the working directory, so I could not read them.

Approach: redirect — Moving the shared logic down into a layer both packages import is better than having each package import the other. Edges between the packages would sit outside the order that `TOOLS.md` documents.

Alternatives considered:
- Keep the subprocess calls — this keeps the packages decoupled, but pays process spawn cost and two copies of the argv logic, and it needs the symlink path resolution. It loses on the duplication, but it was at least a boundary that could not form a cycle.
- Move `append_metric`/`has_metric` and the `view`/`repo` read builders into `.agent/tools/lib` (which `ls_data` already imports from, via `lib.git`). Both packages then import downward and no package-to-package edge exists. This is the one I would build.
- Keep the cross-package imports and update the `TOOLS.md` order — this is cheaper, but it only works if `review_pr_reads` and `task_progress` never import back into the other package. I could not verify that.

Next changes and their cost: a third cross-tool call (for example, `crew-review` reading task state) adds another cross edge, and each one risks a cycle. Moving the helpers into `lib` makes each of these cheap.

1. [attention · 4] **`.agent/tools/task/ls_data.py:27`** (`from review_pr_reads import add_read_parser, read_argv`) — a task module now depends on a review module, and the import is deferred
```
    from review_pr_reads import add_read_parser, read_argv
```
`TOOLS.md:6-9` lists `task_status → task_progress → task_state → …/ls_data` and the `review_*` chain as separate orders. This adds a `task → review` edge, and `review_records → task_progress` adds the reverse `review → task` edge. If `review_pr_reads` or any module it loads imports a `task_*` module, `crew ls` fails with a partial-import `ImportError` only when it reads a PR. The function-local import is what hides this, because a plain load or lint of the module never exercises the edge.
Fix: move the shared `view`/`repo` argv builders (`add_read_parser`, `read_argv`) into `lib`. Alternatively, record the two edges in the `TOOLS.md` order and add a test that imports each package's modules in a fresh interpreter.

2. [attention · 3] **`.agent/tools/review/review_records.py:11`** — `review_records` now imports `task_progress` at module load, so the task and review dependency chains are no longer independent
```
from task_progress import append_metric, has_metric
```
The documented order has no `task_*` module below `review_report`. Loading the `review_*` chain now also loads `task_status` and `task_progress`, and if `task_progress` ever imports review code (for example, to validate a METRIC), the cycle is at module load. `crew-metric.py` and review both call `append_metric`, so the owner is correct, but it belongs in `lib`, not in the task package.
Fix: put `append_metric`/`has_metric` in a `lib` module that both packages import. Otherwise, update the `TOOLS.md` order to say review depends on `task_progress`.

3. [attention · 3] **`.agent/tools/task/ls_data.py:29`** — a bad argv is swallowed as a failed read, and any logic in the `crew-pr-actions.py` entry point is skipped
```
    except (OSError, subprocess.SubprocessError, SystemExit):
        return 1, ""
```
Catching `SystemExit` hides an argparse error (a mismatch between `ls_data`'s argv and the `view`/`repo` parser) as an ordinary "gh failed" read. The PR column would then silently go blank for every row, instead of the break being visible. The in-process path also bypasses whatever the `crew-pr-actions.py` `main` did around `read_argv` (output handling, auth or host selection). That is a second implementation of the read that I could not compare, because the file is not in the package.
Fix: build the argv directly with a `read_argv`-style function, with no parser round trip. Add a test that pins `ls_data`'s argv against the real `view`/`repo` parser, and drop `SystemExit` from the except tuple.

### Findings: 3 (above)