Assessment: comment — the cycle risk is real, but `task_progress.py` and `review_pr_reads.py` are not in the working directory, so I could not check that they behave like the subprocesses they replace.

Read beyond the package: `task_bootstrap.py`. A glob shows the working directory holds only the 4 files named in the change. `task_progress.py`, `review_pr_reads.py` and `lib/git.py` are absent.

1. [attention · 4] **`.agent/tools/review/review_records.py:11`** — `task` and `review` now import each other, with the cycle hidden by a lazy import
```
from task_progress import append_metric, has_metric      # review -> task (module load)
    from review_pr_reads import add_read_parser, read_argv   # task -> review (ls_data, inside function)
```
Before this change the two packages met only through subprocess argv, so neither could break the other's import. Now `review_records` imports `task_progress` at load, and `ls_data` imports `review_pr_reads` from inside a function. That function-level import is the only thing keeping the cycle from showing at load. If a later change moves that import to module level, or `task_progress` starts importing a `review_*` module, `crew ls` and every review will fail at load, and both packages' tests would break together. I found no guard such as an import-direction test or a rule in `AGENTS.md`.
Fix: choose one direction, either `review` depends on `task` or the reverse. Put the shared PR-read helpers (`review_pr_reads`) in a neutral layer such as `lib/`, which `ls_data` already imports from. Then add a test that imports each package alone in a fresh interpreter.

2. [attention · 3] **`.agent/tools/task/ls_data.py:31`** — a failed read is now reported as `(1, "")`, which looks the same as a missing PR
```
    except (OSError, subprocess.SubprocessError, SystemExit):
        return 1, ""
```
`SystemExit` from argparse now means the listing's own argv is wrong, which is a code bug. It is caught together with real environment failures such as gh missing or a timeout. A broken `add_read_parser` contract (for example a renamed flag) would make every PR column silently blank instead of failing loudly. The old subprocess path had the same blind spot, but then the CLI was the stable contract. The parser is now rebuilt in the consumer from a duplicated tuple `("view", "repo")`.
Fix: do not catch `SystemExit`. Have `review_pr_reads` expose a function that takes typed arguments and builds the argv directly, so the listing needs no argparse round trip.

3. [needs more info · 2] **`.agent/tools/review/review_records.py:26`** — does `append_metric` keep the validation and dedup rules `crew-metric.py` had?
```
    if has_metric(owner, f"review run={review_dir.name} "):
    ...
        append_metric(owner, payload)
    except (OSError, ValueError)
```
The old code checked `"METRIC: review run=<name> "` against the raw text of `PROGRESS.md`. Now `has_metric` takes only the part after `METRIC: `. If `has_metric` matches differently (for example by prefix or by line), re-recording could duplicate a line or skip one. The `except` list also assumes `append_metric` raises only `OSError` and `ValueError`. Any other exception would now fail a review that had already persisted, where the subprocess used to contain it. Can you confirm that `has_metric` matches the same string and that `append_metric` raises only those two exceptions? If either is wrong, the cost-line dedup or the "never fail a persisted review" guarantee breaks.