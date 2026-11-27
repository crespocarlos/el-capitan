Assessment: request-changes — the change turns two process boundaries into import edges, and the `ls_data` → `review_pr_reads` edge runs against the documented task → review layering, hidden by a function-level import.

Read beyond the package: `.agent/tools/task/task_bootstrap.py`, `.agent/tools/TOOLS.md`. `task_progress.py` and `review_pr_reads.py` are not in the working directory, so I could not check their import lists or signatures.

1. [attention · 3] **`.agent/tools/task/ls_data.py:26`** — lazy import hides a task→review dependency edge that the documented layering does not have
```
    from review_pr_reads import add_read_parser, read_argv
```
TOOLS.md orders modules as `task_progress` → `task_state` → `ls_data`, and `review_*` modules form a separate chain. This change adds a task→review edge and also keeps the existing review→task edge, since `review_records` imports `task_progress`. If `review_pr_reads` or anything it imports later reaches a `task_*` module, the cycle only shows up at call time, on `crew ls` with a PR. A top-level import would have failed at load. The docstring justifies the lazy import as saving load time, which does not address the cycle risk. Two ordering facts are now implicit and checked by no test.
Fix: Move the shared PR-read helpers (`add_read_parser`, `read_argv`) into `lib/` (next to `lib.git.gh`), so both `crew-pr-actions.py` and `ls_data` depend downward. Otherwise record the task→review edge in TOOLS.md and add a test that imports each module on its own.

2. [attention · 3] **`.agent/tools/task/ls_data.py:28`** — `ls_data` rebuilds the `crew-pr-actions` CLI parser, so the argv grammar has two owners
```
    parser = argparse.ArgumentParser(add_help=False)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("view", "repo"):
        add_read_parser(commands, command)
```
`ls_data` now owns a copy of the subcommand set (`view`, `repo`) and the parse step. If `crew-pr-actions.py` renames a subcommand, adds a required flag, or changes a default, its own CLI and the `ls` callers' argv lists drift apart. The `except SystemExit` then turns that mismatch into a silent `(1, "")`. `crew ls` shows no PR data and gives no error.
Fix: Expose a function in `review_pr_reads` that takes the structured read (command and fields) and returns the argv. Callers then skip the argparse round trip and the `SystemExit` catch.

3. [attention · 3] **`.agent/tools/review/review_records.py:26`** — the new failure contract of `append_metric` may not match the `except` clause that replaced the exit-code check
```
    try:
        append_metric(owner, payload)
    except (OSError, ValueError) as error:
```
The old code reported any non-zero exit of `crew-metric.py`. The new code catches only `OSError` and `ValueError`. If `append_metric` can raise anything else, such as `SystemExit` or a custom error, that exception now propagates out of a review that has already persisted. The docstring says nothing may fail it. The claim that `crew-metric.py` calls `append_metric` too is also unverified, because `task_progress.py` is not in the tree I could read.
Fix: Confirm `append_metric` raises only `OSError` and `ValueError`. Otherwise catch `Exception` at this boundary and log it. Check that `crew-metric.py` delegates to `append_metric`, so there is still one writer.

4. [nit · 2] **`.agent/tools/review/review_records.py:11`** — a review module now imports from the task package at load time
Cost: `review_records` previously had no import-time dependency on `task_*`. It now fails to import if `task_progress` fails, or if the task package is not on `sys.path`. This is probably fine, since the bootstrap lists all packages. TOOLS.md still describes the chains as separate, so the doc is now out of date.