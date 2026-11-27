**Critical**

**"Let the owner close any of them as done"** — The change contradicts the spec's own Summary invariants. The Summary says "only an APPROVED spec may be implemented" and "a DONE task with a PR is read as shipped, approved work". The criteria let a DRAFTING (never approved) task go straight to DONE and attach a PR URL, so unapproved work reads as shipped and approved. This also sidesteps Gate 1 without the owner approving anything.

Fix: decide, and put it under Open questions as `[NEEDS CLARIFICATION: should closing a never-approved task produce DONE, or a distinct closed or abandoned outcome with no PR attached?]`. Add criteria that forbid a DRAFTING-to-DONE close from implying approval.

**Criterion 1 ("any state but DONE")** — The criterion collides with ABANDONED. The Summary calls ABANDONED a side state "only the owner sets", yet the criterion silently lets a forced close revive an ABANDONED task as DONE, and it also covers states like BLOCKED and any in-flight state. The spec doesn't say whether that is intended.

Fix: list the allowed source states explicitly and say what happens from ABANDONED.

**Important**

**Criterion 1 ("The value is logged… a GitHub PR URL is also added")** — The `--pr-url` flag is overloaded as a free-text reason, and "a GitHub PR URL" is not defined. The spec doesn't say how a PR URL is told apart from a reason, or what happens with malformed, empty or non-GitHub values. It also doesn't say what the flag does today, so the semantics may change for existing callers. Two engineers would implement this differently.

Fix: define the validation rule and the behavior for each value class, or use a separate `--reason` flag.

**Criterion 2 and "Owner" (authorization)** — Nothing enforces or tests that only the owner can force-close. The TUI note prompt also has no stated destination, so it isn't clear whether the note is the same value as the CLI reason or a different one. The criterion "every row that is not DONE" is therefore underspecified.

Fix: state how ownership is checked and where the TUI note is persisted, and add a criterion for each.

**Tests and Criterion 3** — The Tests section lists only the lifecycle test command. Task 3 adds `test_tui_model.py` rows, but the TUI test file is not in the Command. The BLOCKED-line criterion has no stated test, and neither does the case where a close from a state with no BLOCKED line leaves state unchanged. "Ends an open BLOCKED line" is also ambiguous about what is written to the file.

Fix: add both test files to the Command and spell out the expected PROGRESS.md and state output for each source state, including DONE (rejected) and a task with no BLOCKED line.

Verdict: 5 finding(s), 1 unverified. The code (`task_gates.py`, the TUI files) is not in the case directory, so I could not check the current `mark_done` or `--pr-url` behavior.