**Critical**

**Acceptance criteria: "`verify --wait <path>` polls the file every 2 s until its `state` is `done`"** — A stale result file is read as the new run's result. The Summary says a task runs verify many times with a fixed default `gates.json`. After the first run leaves `{"state": "done", "verdict": "pass"}`, a builder fixes a bug, runs `verify --background`, then `verify --wait`. The wait can read the old `done` before the child's first write, or while the child is still running. It returns the old pass, and `report-check --gates` then approves a report against gates that did not run on the current code. Nothing requires `--background` to clear or replace the file before it returns, and nothing ties a result to a run (run id, PID, or start time).

Fix: require `--background` to write `{"state": "running"}` with a run id before it exits, and require `--wait` to match that id, with a criterion that a prior `done` file never satisfies a new wait.

**Important**

**Acceptance criteria: "The child writes the result file after each gate"** — A child that crashes, is killed, or whose parent shell exits leaves `state: running` forever. `--wait` then polls for the full 900 s and exits 3, which is indistinguishable from a slow run. Concurrent `--background` runs on the same default path also overwrite each other, and a partial write can be read as invalid JSON.

Fix: add criteria for a dead child (detected via PID and reported as a distinct failure), for atomic write (temp file plus rename), and for a second background run while one is active.

**Acceptance criteria: "`report-check --gates <path>` fails a report that claims a gate the file does not list as passed"** — The check does not require `state` to be `done`. A `running` file lists the gates finished so far, and a report claiming one of them passes. A `fail` verdict whose listed gates include the claimed one also passes. The report can therefore be approved against an unfinished or failed run.

Fix: add criteria that report-check rejects a file whose state is not `done` or whose verdict is not `pass`, and rejects a missing or unparseable file.

**Acceptance criteria: "exits 0 on pass, 1 on fail, 3 after `--timeout`"** — The criteria do not say what happens when `<path>` does not exist, the JSON is malformed, or `--wait` is given with no prior run. Exit code 2 is unassigned. A missing file could poll until timeout, or crash with a traceback that looks like a fail.

Fix: define the behaviour and exit code for a missing or invalid file, and whether the missing-file case fails immediately.

**Consider**

**Acceptance criteria: "starts the gates in a child process and exits 0 at once"** — If the child is tied to the builder's process group or session, it can be killed when the tool call ends, and the spec does not say it must be detached. The cost is a flaky "background" that works in tests and dies in an agent harness.

Verdict: 4 finding(s), 0 unverified (I did not open the codebase, so the claims about `task_verify.py` and `run_all` are unchecked).

Correction: that is 5 findings, not 4. Verdict: 5 finding(s), 2 unverified (`task_verify.py`, `run_all`).