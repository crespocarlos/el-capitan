Assessment: comment — `task_progress`, `review_pr_reads` and `lib.git` are not in the working directory, so I could not check the new in-process contracts or whether the two packages now import each other.

1. [needs more info · 3] **`.agent/tools/review/review_records.py:11`** — review now imports `task_progress` at module load, while `task/ls_data.py` imports `review_pr_reads` (lazily)
```
from task_progress import append_metric, has_metric
...
    from review_pr_reads import add_read_parser, read_argv
```
The diff creates a task→review edge and a review→task edge between the two packages. The lazy import in `ls_data` hides that cycle at load time. It breaks only if `task_progress` (or something it imports) reaches `review_records`, `review_pr_reads` or `ls_data`. Can you confirm `task_progress` and its transitive imports never import the review package, and that `review_pr_reads` never imports `task_progress` or `ls_data`? If they do, the cycle fails at import time in one entry-point order and works in another. The lazy import suggests the author already hit this. A comment in `ls_data` saying so would help, and a test that imports every module cold would catch it. I could not read the two modules, so I cannot rule it in or out.

2. [needs more info · 3] **`.agent/tools/review/review_records.py:26`** — the "already recorded" check changed shape
```
if has_metric(owner, f"review run={review_dir.name} "):
```
The old guard searched PROGRESS.md for `METRIC: review run=<name> `, with the `METRIC: ` prefix. The new call passes a string without the prefix. If `has_metric` does not add the prefix, or matches differently, the idempotency guard fails. A re-run would then append duplicate cost lines, or skip a line that should be written. Does `has_metric` apply the `METRIC: ` prefix and use the same substring match as before? The stake is double-counted cost on every re-persist.

3. [attention · 3] **`.agent/tools/task/ls_data.py:34`** — `ls_data` now depends on the CLI parser surface of the review package
```
for command in ("view", "repo"):
    add_read_parser(commands, command)
...
args = parser.parse_args(arguments)
done = gh(*read_argv(args.command, args), timeout=45)
```
The in-process read keeps the old argv-list `Reader` contract. Every call therefore builds an argparse parser, parses the argv, and rebuilds the gh argv. `task` now depends on the review package's parser internals (`add_read_parser`, `read_argv`) and on argparse behaviour. `SystemExit` is swallowed, so a drift between callers and parsers returns `(1, "")`, which looks like a failed `gh` read, and nothing reports it. Any logic that `crew-pr-actions.py`'s `main` ran around these reads is now skipped, such as repo resolution or error mapping. This is only checkable against that file, which is not in the package.
Fix: change the `Reader` seam to take structured arguments (command plus fields) and call `read_argv` directly. If argv stays, build the parser once at module level, and log the parse failure to stderr instead of folding it into "gh failed".

4. [nit · 2] **`.agent/tools/review/review_records.py:29`** — narrower exception net
```
except (OSError, ValueError) as error:
```
The old code caught every `SubprocessError` and any non-zero exit from `crew-metric.py`. The in-process `append_metric` can raise other types, such as `KeyError` or `UnicodeError` (a `ValueError` subclass, so already caught). The docstring says nothing here may fail a review that already persisted. Whether any other exception can escape depends on code I could not read. Catching `Exception` here would keep that guarantee.