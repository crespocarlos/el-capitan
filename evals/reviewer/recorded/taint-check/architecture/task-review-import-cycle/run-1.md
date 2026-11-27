Assessment: request-changes — the change puts a task→review import edge (lazy, in `ls_data`) beside an existing review→task edge (`review_records`→`task_progress`). That breaks the one-way package order that TOOLS.md states.
Read beyond the package: `task_bootstrap.py`, `TOOLS.md`. `task_progress.py`, `review_pr_reads.py` and `review_bootstrap.py` are not in the working directory, so I could not read what they import.

1. [attention · 3] **`.agent/tools/task/ls_data.py:26`** — a task→review import now runs opposite to the existing review→task import
```
    from review_pr_reads import add_read_parser, read_argv
```
TOOLS.md orders modules so that "a module never imports back into one that imports it". `review_records` now imports `task_progress`, so review depends on task. `ls_data` now imports `review_pr_reads`, so task depends on review. If `review_pr_reads` or the modules it imports (directly or through others) ever import `task_state`, `ls_data` or anything else that reaches `ls_data`, the cycle is real. The lazy import hides it until the first PR read, so `crew ls` would then fail at runtime rather than at load. The unread `review_pr_reads` imports mean I cannot rule that out today. The shell-out used to be the decoupling boundary, and this change removes it.
Fix: move the shared PR-read helpers (`add_read_parser`, `read_argv`) into `lib/` (for example `lib/pr_reads.py`). Both `ls_data` and `crew-pr-actions` can then import from there, and neither package imports the other.

2. [attention · 3] **`.agent/tools/task/ls_data.py:28`** — `ls_data` rebuilds the `crew-pr-actions` CLI parser to get at an argv builder
```
    for command in ("view", "repo"):
        add_read_parser(commands, command)
    ...
        args = parser.parse_args(arguments)
        done = gh(*read_argv(args.command, args), timeout=45)
```
The caller already holds `arguments` as a CLI argv. `ls_data` parses it with a hand-built parser, then converts it back into gh argv. The `("view","repo")` list is a second copy of which subcommands count as reads. If `review_pr_reads` adds a required flag or renames a subcommand, `ls` hits `SystemExit`, which is swallowed into `(1, "")`. The PR column then goes blank with no error. The old subprocess call at least surfaced the failure on stderr.
Fix: have `review_pr_reads` expose a function that takes typed parameters, such as `read_view(url)`. `ls_data` should call it directly with no argparse round trip, and the `Reader` signature should carry those parameters.

3. [attention · 3] **`.agent/tools/task/ls_data.py:34`** — an import failure is not covered by the handler, and the swallow hides contract drift
```
    except (OSError, subprocess.SubprocessError, SystemExit):
        return 1, ""
```
The `from review_pr_reads import ...` line sits outside the `try`. If the review package is missing or broken, `ImportError` aborts the whole `crew ls`. The old subprocess isolated that failure to one PR read. Catching `SystemExit` also turns a programmer error, such as a parser mismatch, into a quiet "no PR". The change adds no flag and no test to notice either case.
Fix: move the import inside the `try` and add `ImportError` to the handler. Print one stderr warning when the cause is a parse error or an import error rather than a gh failure.