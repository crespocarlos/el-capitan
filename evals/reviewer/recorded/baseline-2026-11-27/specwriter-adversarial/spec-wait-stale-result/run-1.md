**Critical**

**"The result file is `<TASK_DIR>/gates.json` by default (`--out` overrides it). A task runs verify many times"** — A stale `done` file from an earlier run makes `--wait` return the old verdict.

The same default path is reused on every run. If `--wait` is called right after `--background` and before the child's first write, it sees the previous run's `state: done`. It then returns a stale pass or fail. `report-check --gates` has the same problem: it could validate a report against gates from a previous run, which defeats "the gates that really ran". The spec has no run identity and no rule that the file is reset before the parent returns.

Fix: Require each run to be distinguishable, for example a run id that `--wait` matches. Also require the file to be reset to `running` before `--background` exits, and add a criterion that waiting after a second run never returns the first run's verdict.

**Important**

**"`verify --wait <path>` polls the file every 2 s until its `state` is `done`... 3 after `--timeout`"** — There is no failure path for a child that dies.

If the child crashes, is killed, or hits an exception in a gate, the file stays at `running` forever. `--wait` then burns the full 900 s and exits 3, which looks the same as a slow run. A missing file, a corrupt or half-written JSON file, and a file that was never created are also unspecified.

Fix: Add criteria for child death (for example a `state: error` or a pid/liveness check) and for a missing or unparseable file. Also require atomic writes so a poll never reads a partial file.

**"`report-check --gates <path>` fails a report that claims a gate the file does not list as passed."** — This is ambiguous and not tied to the run state.

It doesn't say what happens when `state` is `running`, when the verdict is `fail`, or when the report omits gates that did run. It also doesn't say how a claimed gate is matched to a gate in the file, or what the exit code and message are.

Fix: Define the behavior for each `state` and verdict, the matching rule, and the exit code. Add a test for each.

**"## Tests ### Unit"** — Coverage is one happy-path row.

This is a cross-process feature with exit codes and a CLI. There are no tests for the fail verdict (exit 1), the timeout (exit 3), `--out`, stale files, concurrent runs, or `report-check`. Task 3 doesn't list `report-check` at all, and no task implements the `report-check --gates` criterion.

Fix: Add a test for each exit code and for the stale and child-crash cases. Add a task and tests for the `report-check` change.

**"starts the gates in a child process and exits 0 at once"** — Concurrent runs are unspecified.

A second `--background` run to the same path, for example after a fix while the first is still going, would interleave writes in the same file. The spec doesn't say whether to reject it, kill the first run, or queue it.

Fix: State the policy for a run that starts while another is `running`, and add a criterion for it.

Verdict: 4 finding(s) (the grouped count above is 5 including the Critical one), 2 unverified: `task_verify.py` and `report-check` existing behavior were not read, and the originating issue was not opened.