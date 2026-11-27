**Critical**

**AC "`verify --wait <path>` polls the file every 2 s until its `state` is `done`"**: the spec itself says "A task runs verify many times", and the result file defaults to the same `<TASK_DIR>/gates.json`. A stale `done` file from the previous run is therefore still there. If the builder runs `--background` and then `--wait`, the wait can read the old `done` before the child has written anything. It then returns the previous verdict, and `report-check` accepts gates that did not run in this run. Nothing in the criteria says the file is reset when the run starts, or how `--wait` knows the file belongs to this run. Fix: add a criterion that `--background` removes or overwrites the result file with `state: running` and a run id before it returns, and that `--wait` only accepts a `done` result with the matching run id.

**Important**

**AC "The child writes the result file after each gate"**: the write is unspecified as atomic, and the child's failure is not covered. If the waiter reads while the child is mid-write, it sees truncated JSON. If the child crashes or is killed, the file stays `running` forever and `--wait` blocks until the 900 s timeout. Fix: require atomic writes (temp file plus rename), and require a `state: "error"` result, or a liveness check on the child pid, so `--wait` exits non-zero promptly.

**AC "`report-check --gates <path>` fails a report that claims a gate the file does not list as passed"**: the criterion does not say what happens when the file is `running`, missing, or from a stale or failed run. A literal build checks only the gates list, so a half-finished `running` file can pass a report. Fix: add a criterion that `report-check` fails unless `state` is `done`, and that it fails when the file is missing or malformed.

**AC "exits 0 on pass, 1 on fail, 3 after `--timeout`"**: exit code 3 is unverified against the existing exit codes of `crew-task.py`. Also, `--wait` on a missing path or malformed JSON is undefined. Concurrent `--background` runs on the same `--out` would overwrite each other. Fix: state the exit code for a missing or corrupt file, and for a second background run while one is still `running`.

Verdict: 3 finding(s), 4 unverified (no files read: exit-code conventions, `run_all` structure, the `report-check` code, and the existing `--out` semantics)