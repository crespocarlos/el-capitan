Verification found no case files. `task_gates.py` and `mark_done` do not exist in the working directory, so every claim about the code is unverified.

**Critical**

**Acceptance criteria, first bullet: "closes a task in any state but DONE as DONE"** — A DRAFTING or unapproved spec closes as DONE with a PR URL. This contradicts the Summary: "a DONE task with a PR is read as shipped, approved work", and Gate 1 approval is the owner's alone. A GitHub PR URL for a spec that never passed `mark-approved` would be added to the PR list, so stale clutter would show up as shipped, approved work. The same literal build lets a forced close also overwrite ABANDONED, the "side state only the owner sets".

Fix: state how a close from a never-approved state is recorded, for example with no PR attached and a distinct reason marker, and add a criterion that a forced close never adds a PR or any approval record to a task that has not passed Gate 1. Put the ABANDONED case under `## Open questions`.

**Important**

**Acceptance criteria, first bullet: "`--pr-url <value>` … The value is logged in PROGRESS.md as the reason"** — `--pr-url` is overloaded as a free-text reason. A non-URL value such as "dropped" is accepted silently, and a URL meant as a reason is promoted to the PR list. The TUI's "note prompt" has no stated mapping to this flag. Two builders would read it differently.

Fix: define the flag semantics. Either add a separate `--reason` flag, or specify validation and say how the TUI note maps onto the flag.

**Acceptance criteria, third bullet: "A forced close ends an open BLOCKED line"** — Nothing says what "ends" means in the file, what happens when no BLOCKED line is open, or what happens when several are. Nothing says which wins if the task's state and its BLOCKED line disagree. Only the happy path is stated.

Fix: specify the exact BLOCKED-line change, and add criteria for the no-line and multiple-line cases.

**Missing criteria: "what must stay impossible"** — Without `--force`, the old IMPLEMENTING-only check must still reject closing from other states. A DONE task must be rejected with no PROGRESS.md change. Concurrent or double closes must not append duplicate PR entries or log lines. The TUI's "every row that is not DONE" is also unspecified for a missing or empty note, and for the case where the CLI rejects the close.

Fix: add negative criteria for the non-force path, a repeat close of a DONE task, and the TUI's handling of an empty note or a CLI rejection.

Verdict: 4 finding(s), 4 unverified: `task_gates.py` `mark_done`, `tui/tui_model.py` `moves`, the BLOCKED-line handling, and the existing `--force` behaviour. None of these files exist in the case directory.