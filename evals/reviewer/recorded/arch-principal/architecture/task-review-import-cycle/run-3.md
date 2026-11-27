Assessment: approve — in-process calls replace subprocess hops with one writer or reader each, and the module cycle is avoided by a lazy import; the remaining risks are unverified behaviour parity and an undocumented cross-package edge.

Read beyond the package: `.agent/tools/TOOLS.md`, `.agent/tools/task/task_bootstrap.py`. I could not read `task_progress.py`, `review_pr_reads.py` or `crew-pr-actions.py`, because they are not in the working directory.

Approach: endorse — direct imports of the shared reader and writer beat subprocess hops, which carry an interpreter start-up cost and an argv/exit-code contract. Alternative: keep the subprocess boundary and fix only the call sites.

Alternatives considered:
- Keep shelling out — this keeps the tools isolated, but the same METRIC dedupe and format rule is then reached through argv. The change already goes through `append_metric`, which `crew-metric.py` also calls, so there is one writer and no divergence.
- Move the PR reads and the metric writer into `lib/` — this would remove the task↔review package edge entirely. It is a larger move and not needed now, but it is the cleaner end state, because the documented import order currently covers neither new edge.

1. [attention · 3] **`.agent/tools/task/ls_data.py:24`** — a task-package module now depends on the review package, and the documented import order does not say so
```
from review_pr_reads import add_read_parser, read_argv
```
`TOOLS.md` lists the order `task_progress` → … → `ls_data`, and `review_records` now imports `task_progress`. So task and review depend on each other at package level, and only this function-local import keeps the module graph acyclic. If someone hoists the import to module level, or `review_pr_reads` later imports a task module, `crew ls` fails with an ImportError at load. This is a new fact with no owner in `TOOLS.md`.
Fix: record the edge in the `TOOLS.md` dependency order (`review_pr_reads` as a leaf that imports nothing from `task`). Move `review_pr_reads` to `lib/` or the task package if it is shared.

2. [attention · 3] **`.agent/tools/task/ls_data.py:28`** — the in-process read may skip behaviour that `crew-pr-actions.py`'s `main` provided
```
args = parser.parse_args(arguments)
done = gh(*read_argv(args.command, args), timeout=45)
```
This rebuilds the argparse wiring and dispatch of `crew-pr-actions.py`. If that entry point did post-processing, such as a repo default, output normalization or exit-code mapping, `crew ls` no longer gets it. A `view` that used to be normalized would return raw `gh` output to the `ls` parser. I could not read the entry point to confirm, so I am scoring this at 3.
Fix: expose a single `review_pr_reads.run_read(argv)` that `crew-pr-actions.py` also calls, so `ls_data` does not duplicate the parser setup.

3. [nit · 3] **`.agent/tools/task/ls_data.py:21`** — the parser is rebuilt on every read
Each PR read constructs a new `ArgumentParser` with two subparsers. A listing with many PRs repeats this, which is small but avoidable. Catching `SystemExit` also hides argparse's stderr message.
Fix: build the parser once, or call `read_argv` directly with the known command.