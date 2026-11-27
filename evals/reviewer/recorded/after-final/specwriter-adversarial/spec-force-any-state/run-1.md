**Critical**

**Acceptance criteria, criterion 1: "closes a task in any state but DONE as DONE … a GitHub PR URL is also added to the task's PR list"**: this contradicts the Summary, which says "only an APPROVED spec may be implemented, and a DONE task with a PR is read as shipped, approved work."
- Failure scenario: a DRAFTING spec that was never approved is force-closed with a GitHub PR URL. It becomes DONE with a PR attached and reads as shipped, approved work, so Gate 1 is bypassed.
- The criteria never say what separates "dropped" from "shipped" for tasks closed from pre-APPROVED states.
- Fix: add a criterion that a forced close from a state before APPROVED does not add a PR to the PR list and is recorded as not approved or not shipped. Otherwise put the question under `## Open questions`.

**Important**

**Acceptance criteria, criterion 1: "`--pr-url <value>` … The value is logged … as the reason"**: one flag carries two meanings, a URL or a free-text reason, and the spec doesn't say how to tell them apart.
- A builder could test for "starts with https://github.com", accept any string, or reject a non-URL. A reason like "dropped, see github.com/x/pull/1" is ambiguous.
- The TUI "note prompt" is never mapped to this flag. It is unclear whether the note becomes `--pr-url` or a separate field.
- Fix: define the parsing rule for a GitHub PR URL versus a plain reason, and state how the TUI note maps onto the CLI arguments.

**Acceptance criteria, criterion 1: "any state but DONE"**: this includes ABANDONED, which the Summary says is "a side state only the owner sets". It also includes IMPLEMENTING with a live agent.
- Failure scenario: a background agent or non-owner runs `--force` on an ABANDONED task. The owner's decision is reversed and nothing checks who ran it.
- A running implementation can be marked DONE underneath its worktree or lock.
- No criterion enforces "owner", and none says whether ABANDONED and in-flight tasks are exempt.
- Fix: add criteria for who may force-close, whether ABANDONED is allowed, and what happens to an active implementer.

**Acceptance criteria, criterion 3: "A forced close ends an open BLOCKED line"**: it is unclear whether BLOCKED is a state or a line in PROGRESS.md, and what "ends" means (a closing entry, deletion, or a state change).
- A builder could write an end marker, delete the line, or only handle tasks currently in BLOCKED. The result could be a DONE task that still shows as blocked in `crew ls`.
- Fix: define the BLOCKED representation and the exact resulting PROGRESS.md and `crew ls` output.

**Consider**

**Acceptance criteria: missing negatives for existing behaviour**: nothing says `mark-done` without `--force` still rejects non-IMPLEMENTING states, that a DONE task still errors under `--force`, or what the exit code is. Existing scripts depend on the current rejection. The cost is a regression that goes unnoticed.

Verdict: 5 finding(s), 5 unverified. I did not read `task_gates.py`, the TUI model, or the existing owner and state checks, so the claims about current behaviour, owner enforcement, and BLOCKED representation are unverified.