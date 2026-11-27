**Critical**

**"every write under `~/.agent/tasks` (PROGRESS.md, REPORT.md, checkbox ticks in SPEC.md) prompts today, so builders stall."** — The blanket allow defeats Gate 1 and the review evidence.

The spec's second paragraph says the directory holds what the gates trust: the `## Status` line, `.task-id`, and `review/*.expect` nonces and saved replies. The criteria still allow `Edit` and `Write` on `~/.agent/tasks/**` and remove the ask rule on SPEC.md. A background builder can then set Status to APPROVED, rewrite `.task-id`, or forge review evidence with no prompt, and the owner-only approval no longer holds. The motivating complaint covers only PROGRESS.md, REPORT.md and checkbox ticks, so the mechanism is much broader than the problem.

Fix: Scope the allow to the files builders need to write. Keep ask or deny on the Status line, `.task-id` and `review/`, or put an explicit question under `## Open questions` on how those stay protected.

**Important**

**Acceptance criteria (no negative criterion)** — Nothing proves the gate files are still protected.

The criteria only test that writes succeed. None asserts that a write to the Status line, `.task-id` or `review/*` still prompts or is denied, and Task 2's fixtures would pass with the gates fully open.

Fix: Add criteria and fixture rows that assert the gate-trusted paths are not auto-allowed.

**"removes the old ask rule for task SPEC.md files"** — A path-scoped permission cannot separate a checkbox tick from a Status edit within SPEC.md.

Both are Edits to the same file, so the spec contradicts itself. It says Gate 1 is the owner moving Status to APPROVED through `crew-task.py mark-approved`, yet it also removes the only rule that guards that file. The spec doesn't say how a builder tick is told apart from an approval, or whether `mark-approved` is the only writer.

Fix: State which mechanism enforces "only `mark-approved` changes Status", or list it under `## Open questions`.

**"A background builder ticks a SPEC.md checkbox … with no prompt"** — The test layer doesn't match the claim.

`install.sh` fixtures check the settings merge. They can't show that a real background builder runs unprompted, and that behavior depends on Claude Code's permission precedence (deny > ask > allow, and whether `additionalDirectories` interacts with `Edit` rules). The spec leaves this unstated.

Fix: Add a criterion or test that evaluates the merged settings against concrete paths, or document the precedence assumption.

**"Uninstall removes exactly the entries install added."** — This is under-specified for entries that already exist.

If the user already had `~/.agent/tasks` in `additionalDirectories` or an equivalent allow rule, uninstall would delete the user's own entry. The removed ask rule is never restored, so the install/uninstall round trip is not symmetric. Re-running install also has no idempotency criterion.

Fix: Add criteria for pre-existing entries, idempotent re-install, and whether uninstall restores the ask rule.

Verdict: 4 finding(s), 3 unverified (I read no files: `merge_claude_settings.py`, `install.sh`, and the existing ask rule and permission-precedence behavior were not checked.)