Assessment: request-changes — it replaces two subprocess seams with in-process calls, but the new `task` → `review` import in `ls_data` closes a package-level cycle that only a function-local import keeps from failing.

Read beyond the package: `.agent/tools/task/task_bootstrap.py`, `.agent/tools/TOOLS.md`, and a grep of the tools tree for imports. `task_progress.py`, `review_pr_reads.py` and `crew-metric.py` are not in the working directory, so I could not read them.

Approach: redirect — in-process calls are the right goal, but the `ls_data` side should not import from the `review` package. Move the PR read helpers to a neutral module, or keep the subprocess for that one edge.
Alternatives considered:
- Keep the subprocess calls (don't build it) — this keeps the packages decoupled and the `crew-*.py` CLIs as the stable contract. It loses on cost: about 45 s of timeout handling and a Python startup per read, and two writers that must agree on the METRIC format. It is still better than a hidden cycle for the `ls_data` edge.
- Move `add_read_parser`, `read_argv` and the metric helpers into `lib/`, which both packages already import (`lib.git`) — this keeps the dependency direction clean. It wins on the cycle, and I would pick it. It costs one move.
- The chosen design (lazy import of `review_pr_reads` inside `read_pr_actions`) — this is the smallest diff. It loses on structure, as finding 1 shows.

1. [attention · 4] **`.agent/tools/task/ls_data.py:26`** — `task` → `review` import closes a package cycle behind a lazy import
```
    from review_pr_reads import add_read_parser, read_argv
```
`review_records` now imports `task_progress` (review → task), and `ls_data` imports `review_pr_reads` (task → review). `TOOLS.md` says "a module never imports back into one that imports it", and its dependency chain lists `ls_data` after `task_progress` with no review modules in it. Moving this import to module top, or any new import from `review_pr_reads` into `task_*`, would raise an ImportError, but only on the path that reads a PR. A later edit that gives `review_pr_reads` a `task_*` import would pass import checks and fail only when `crew ls` reads a PR. Neither module nor `TOOLS.md` records the edge. `ls_data` also no longer calls `review_bootstrap`, so it relies on `task_bootstrap` having put the `review` directory on `sys.path`, which the `PACKAGES` tuple happens to do.
Fix: move the PR read parser and argv builder into a module both packages may import (for example `lib/pr_reads.py`), import it at top level, and update the dependency chain in `TOOLS.md`.

2. [attention · 3] **`.agent/tools/task/ls_data.py:30`** — the parser is rebuilt on every call and `SystemExit` is swallowed
```
    parser = argparse.ArgumentParser(add_help=False)
    ...
    except (OSError, subprocess.SubprocessError, SystemExit):
```
`ls_data` re-parses an argv it built itself, using the parser definitions from another package. If `add_read_parser` gains a required flag, `parse_args` raises `SystemExit`, and every PR read in `crew ls` returns `(1, "")`. The listing then shows PRs as unreadable, with nothing logged. Previously the same drift would have produced a visible stderr message from the subprocess. A failure to read looks the same as a genuinely missing PR.
Fix: have `review_pr_reads` expose a function that takes `view` or `repo` plus plain values and returns the gh argv, so no parse step is needed. Keep `SystemExit` out of the catch.

3. [needs more info] **`.agent/tools/review/review_records.py:11`** — I could not verify the `append_metric` and `has_metric` contract
`task_progress.py` is not in the package. The old guard checked `PROGRESS.md` for `METRIC: review run=<name> `, and `crew-metric.py` validated the payload and returned a non-zero exit code. The new code catches only `OSError` and `ValueError`. Question: does `append_metric` raise only those two types on a bad payload or a failed write, and does `has_metric` match the same `METRIC: review run=…` prefix as before? If it raises something else, such as `KeyError` or a custom error, a review that has already persisted would crash at its final step. If the prefix differs, re-running a review would append a duplicate cost line.

Handoff to adversarial: `.agent/tools/task/ls_data.py:31` — `gh(..., timeout=45)` replaces `subprocess.run`. Confirm that `lib.git.gh` raises `OSError` or `SubprocessError` for a missing binary or a timeout, and does not return a result object that hides the failure.