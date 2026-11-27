**Critical**

**"The result file is `<TASK_DIR>/gates.json` by default (`--out` overrides it). A task runs verify many times"** — A stale result file from a previous run is never handled. `--wait` can read an old `state: done` from run N-1 and return that verdict before the new child has written anything. `report-check --gates` can likewise approve a report against an old file. Because the file is reused and verify runs many times, this is the normal case, not an edge case.

Fix: Add criteria saying that a run identifies itself (for example a run id or a reset of the file at start), that `--wait` only accepts the result of the run it was pointed at, and that the file is cleared or marked `running` before `--background` returns.

**Acceptance criteria 1 and 2 (start and write ordering)** — `--background` exits 0 "at once", but the child may not have written its first `running` state yet. A `--wait` issued right after sees either no file or the previous run's file. Nothing says whether a missing file is an error or something to keep polling for.

Fix: Add a criterion that the initial `running` state is written before `--background` exits, and define the behavior of `--wait` when the file is missing or unparseable.

**Important**

**Acceptance criterion 2 (child crash)** — If the child crashes, is killed, or its gate hangs, the file stays `running` forever. `--wait` then burns the full 900 s and exits 3, which gives the builder no cause. A truncated file from a non-atomic write can also break the poller's JSON parse.

Fix: Add criteria for a failed child (a `state: error` or a recorded pid and liveness check) and for atomic writes (temp file plus rename).

**Acceptance criterion 4 (`report-check --gates`)** — "fails a report that claims a gate the file does not list as passed" does not say what happens when the file is `running`, missing, or `fail`. It also doesn't say how a "claimed gate" is read from the report. The Summary goal that the report states "the gates that really ran" is not fully covered either, since a report that omits gates passes this check. No task implements this criterion: Tasks 1–3 only touch `task_verify.py`.

Fix: Specify the report-check behavior for each state, how claims are parsed, and add a task for it.

**Tests / Unit** — There is a single test, and it uses a "fresh task directory", which is the one case that hides the stale-file bug. Nothing covers exit codes 1 and 3, the report-check criterion, or a rerun in the same directory.

Fix: Add tests for a rerun in the same directory (stale file), fail and timeout exits, a crashed child, and `report-check --gates`.

Verdict: 4 finding(s), 0 unverified. The spec was judged from its text alone and I read no code. Whether `run_all` and `report-check` exist as the spec describes was not checked.