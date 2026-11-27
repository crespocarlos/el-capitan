**Critical**

**"Let the owner close any of them as done, from the CLI and from the TUI."** — The design closes an unapproved spec as DONE, which contradicts the Summary's own gate rules.

The Summary says "only an APPROVED spec may be implemented, and a DONE task with a PR is read as shipped, approved work." The criteria let a DRAFTING or never-approved task go to DONE, and they add a PR URL to the PR list. That makes unreviewed work look shipped and approved, so Gate 1 is bypassed. The spec also says ABANDONED is "only the owner sets", and that state fits "approved work that was dropped" and "never approved" specs better. The spec never says why DONE is the right terminal state for those cases.

Fix: put this under Open questions as `[NEEDS CLARIFICATION: should dropped or unapproved tasks close as ABANDONED, or as DONE with a marker that tells them apart from shipped work?]`. If DONE stays, state that a forced close from a pre-APPROVED state must not look like approved or shipped work.

**Important**

**Criterion 1 (`--pr-url <value>` is the reason)** — One argument does two jobs, and the criterion leaves out what happens in the cases that matter.

The value is both a free-text reason and, if it looks like a GitHub PR URL, a PR-list entry. The spec doesn't say how a PR URL is recognised. It doesn't say what happens with a malformed or non-GitHub URL, or with an empty value. The TUI's "note prompt" has no stated mapping to this argument. A task closed with a PR URL is "read as shipped," so a stale spec with a PR URL attached would pass as shipped.

Fix: use a separate reason argument (or state the parsing rule), and add criteria for an empty value, a non-URL value, and the TUI note mapping.

**Criterion 3 and "any state but DONE"** — The BLOCKED handling and the other state edge cases are underspecified.

"Ends an open BLOCKED line" doesn't say what it writes or where. It doesn't say whether a BLOCKED task keeps that status or moves to DONE. It doesn't say what happens if a task has no BLOCKED line, or what a forced close on a DONE task or an ABANDONED task does. The criterion "any state but DONE" has no negative case (an error message and exit code for DONE).

Fix: add criteria for the exact BLOCKED-closure output, for rejecting DONE, and for the ABANDONED and no-BLOCKED-line cases.

**Tests** — The Unit-only block doesn't cover the TUI or the CLI as users run them.

The TUI affordance and the CLI flags are tested only through `test_lifecycle.py`. The Tasks section names `test_tui_model.py`, but the Tests command doesn't run it. Nothing checks the "every row not DONE" rendering or the note prompt.

Fix: add `test_tui_model.py` to the Tests command, and add an Integration or E2E entry for the CLI invocation and the TUI flow.

**Consider**

**Criterion 2 (owner)** — Nothing enforces "owner" in the criteria. The Summary says the owner closes tasks, but no criterion or task checks who is running `--force`. Fix: say whether `--force` is the whole owner check, or add a criterion.

Verdict: 4 finding(s), 1 unverified. I couldn't verify the `task_gates.py`, `tui_model.py` and test file claims. The case directory holds only SPEC.md, and the grep found no `mark_done` code.