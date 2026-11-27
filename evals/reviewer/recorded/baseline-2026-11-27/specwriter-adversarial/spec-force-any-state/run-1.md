**Critical**

**Summary: "Let the owner close any of them as done"** — Closing as DONE bypasses Gate 1 and makes unapproved work look shipped.

The spec says "only an APPROVED spec may be implemented, and a DONE task with a PR is read as shipped, approved work." Yet the criteria let a DRAFTING (never approved) or abandoned task become DONE, and attach a PR URL to it. The spec never settles whether DONE now means "shipped", or only "closed". This is a premise contradiction, and the stale-clutter complaint also covers dropped work, which already has ABANDONED. The spec doesn't say why a DRAFTING or dropped task should be DONE and not ABANDONED.

Fix: put under Open questions whether DRAFTING and dropped tasks should close as ABANDONED instead. If DONE stays, state how a forced close of an unapproved task is kept distinguishable from shipped work, for example no PR attached or a visible marker.

**Important**

**AC1, `--pr-url <value>`** — One argument is used both as a free-text reason and as a PR URL.

"The value is logged … as the reason; a GitHub PR URL is also added" does not define what counts as a GitHub PR URL. It also doesn't say what happens with an empty value, a non-GitHub URL, or a malformed one. Two implementers would handle these differently. The semantics are also odd: forcing a close of a task that has no PR would seem to call for a separate reason flag, and the spec doesn't say whether `--pr-url` is required.

Fix: define the validation rule and the error behavior, and say whether reason and PR URL are separate inputs.

**AC2, TUI "close as done … with a note prompt"** — The note's fate is unspecified, and there is no confirmation step.

The spec doesn't say whether the note maps to the `--pr-url` value or goes to PROGRESS.md. It also doesn't say what an empty note does, or what the TUI does with a PR-less close. A one-key irreversible state change, with no stated confirmation, is risky.

Fix: state the mapping from note to reason or PR, the empty-note behavior, and the confirmation requirement.

**AC3, "A forced close ends an open BLOCKED line"** — "Ends" is ambiguous, and the BLOCKED state model is not described.

The criterion doesn't say how a BLOCKED line is ended: removed, closed with a marker, or timestamped. It also doesn't say what happens when the task has no BLOCKED line or has several. It doesn't say whether a task in BLOCKED state is covered by "any state but DONE".

Fix: define the end-of-BLOCKED representation and the no-line and multiple-line cases.

**Tests / Criteria coverage** — There are no criteria or tests for rejection paths or ownership.

Nothing covers a force close of a task that is already DONE (should error), a missing `--force`, or a non-owner caller, even though the spec says "the owner" closes tasks. The only Tests entry is a unit command for `test_lifecycle.py`. It doesn't run `test_tui_model.py`, which Task 3 edits. The TUI behavior also has no integration coverage.

Fix: add criteria and tests for the DONE rejection, the non-owner and missing-`--force` cases, and the TUI path, and include `test_tui_model.py` in the Tests command.

**Unverified:** I did not find `.agent/tools/task/task_gates.py`, `tui/tui_model.py` or the tests in the working directory, so I could not check the current `mark_done` behavior, the state names, or the BLOCKED representation. The originating issue is unverified too.

Verdict: 5 finding(s), 3 unverified (task_gates.py mark_done, tui_model.py moves, BLOCKED representation)