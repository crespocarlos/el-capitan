**Critical**

**"Add `--background`, which starts the run and returns at once, and `--wait <path>`, which blocks until the run is finished and prints its verdict."**: The result file is reused across runs, so `--wait` can return a previous run's verdict.

The spec says "A task runs verify many times" and writes to the same `<TASK_DIR>/gates.json` by default. Nothing requires `--background` to reset the file before it returns. If `--wait` runs before the child's first write, it sees the earlier `state: "done"` and returns that old pass or fail. The same stale file feeds `report-check --gates`, so a report can be validated against gates that did not run this time. The only test uses a fresh directory, which hides this.

Fix: Add a criterion that `--background` writes `state: "running"` (with a run identifier) before it exits, that `--wait` and `report-check` only accept a result from that run, and a test that re-runs verify over an existing `done` file.

**Important**

**Acceptance criteria 2–3 (child failure)**: A child that crashes or is killed leaves the file at `running` forever, and nothing defines that case.

`--wait` would then poll for the full 900 s and exit 3, which looks the same as a slow run. The criteria also don't say what happens if the file is missing or malformed, or if the child exits without writing `done`. They don't say what `report-check` does with a `running` file either.

Fix: Add criteria for child death (for example, a recorded pid or an `error` state that `--wait` reports promptly), and for the missing, corrupt and still-`running` states in both `--wait` and `report-check`.

**Acceptance criteria 2 (partial writes and concurrency)**: The file is rewritten after each gate while another process polls it.

A non-atomic write can show `--wait` or `report-check` a truncated JSON file. Two overlapping `--background` runs on the same `<TASK_DIR>` would also overwrite each other's results, and the spec doesn't say whether that is allowed.

Fix: Require atomic replacement of the result file and state the rule for a second concurrent run on the same path.

**Acceptance criteria 4 (`report-check --gates`)**: The criterion is vague and has no test.

"Claims a gate" and "listed as passed" are undefined, since the report format isn't specified. The Tests section has no `report-check` case at all. The only test covers background plus wait, so criterion 4 and the exit codes 1 and 3 are unverified.

Fix: Define how a gate claim is matched to the file, and add tests for fail (exit 1), timeout (exit 3) and `report-check` with a missing gate.

**Consider**

**Tests / Acceptance criteria 1**: Nothing checks that `--background` returns at once, that the detached child survives the parent exiting, or what `--out` does when combined with `--wait`.

Fix: Add a test that the parent exits before the gates finish and that `--out` is honoured.

Verdict: 5 finding(s), 1 unverified. I did not read `task_verify.py`, `run_all` or the existing tests, so I could not confirm how the current code handles the result file or whether it already resets it.