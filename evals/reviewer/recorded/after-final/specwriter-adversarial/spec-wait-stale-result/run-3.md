**Critical**

**Acceptance criteria: `verify --wait <path>` polls the file every 2 s until its `state` is `done`** — a stale result file from an earlier run satisfies the wait.

The Summary says a task runs verify many times and writes to the same default `gates.json`. Run 1 leaves `state: done, verdict: pass`. Run 2 starts with `--background`, and the child hasn't yet overwritten the file. `--wait` reads the old `done`, exits 0 on the stale pass, and the builder or report-check trusts gates that didn't run on the current code. The same happens if the child crashes before its first write.

Fix: add a criterion that `--background` removes or resets the result file before it returns, and give each run an identity (a run id or the child's pid) that `--wait` must match.

**Important**

**Acceptance criteria: `The child writes the result file after each gate`** — the write is not atomic, and a dead child leaves `running` forever.

The poller can read a half-written JSON file and crash or misparse it. If the child is killed or crashes mid-run, the file stays `running`, and `--wait` blocks for the full 900 s and exits 3. That is indistinguishable from a slow run.

Fix: require atomic writes (temp file plus rename), tolerate an unparseable read by retrying, and have `--wait` detect a dead child (recorded pid) and report an error state.

**Acceptance criteria: `exits 0 on pass, 1 on fail, 3 after --timeout`** — no behaviour is defined for a missing path or a crashed run.

`--wait` on a nonexistent file, or a gate that errors instead of failing, has no stated exit code. Exit code 1 is ambiguous with a verdict of fail, and the criteria don't say what `--timeout` does to the still-running child.

Fix: add criteria for a missing or unreadable file and for an errored gate, each with a distinct exit code, and state whether the child is killed on timeout.

**Acceptance criteria: `report-check --gates <path>` fails a report that claims a gate the file does not list as passed`** — it doesn't check the state.

If the file is `running` or stale, report-check reads a partial gate list. A report written while verify is still running would then wrongly fail, or a stale file would wrongly pass. Nothing requires `state: done`, and nothing ties the result to the current commit.

Fix: require report-check to reject a non-`done` file and a file older than the last change (record a commit SHA in the result).

**Acceptance criteria: `verify --background` … exits 0 at once`** — concurrent runs on the same output path.

Two `--background` runs on the same `<TASK_DIR>/gates.json` (after a batch, and then after a fix) interleave their writes, and the earlier child can overwrite the later one's results.

Fix: add a criterion that a second `--background` to a path with a live run is refused or supersedes the first, which is then killed.

Verdict: 4 finding(s), 0 unverified (I did not read the case files, so the claims about `task_verify.py` and `run_all` are unchecked).