**Critical**

**"every write under `~/.agent/tasks` (PROGRESS.md, REPORT.md, checkbox ticks in SPEC.md) prompts today, so builders stall"** — A blanket `Edit/Write(~/.agent/tasks/**)` allow removes the guard on the files the gates trust.

The spec's second paragraph says the directory holds the `## Status` line (Gate 1), `.task-id` and `review/*.expect` nonces. Allow rules match on path, so an unattended builder could set Status to APPROVED, rewrite `.task-id`, or forge review evidence. Removing the old ask rule on SPEC.md takes away the one prompt that stopped this. The spec names the trust surface but never says how it stays protected.

Fix: put this under `## Open questions` as `[NEEDS CLARIFICATION: how do builders write only PROGRESS.md, REPORT.md and checkbox ticks while Status, .task-id and review/** stay owner-only?]`, and don't grant the blanket allow until that is answered.

**Acceptance criteria** — Nothing proves the gate files are still protected, and the three criteria only cover the happy path.

An implementation that opens the whole directory satisfies all three criteria. No criterion says a builder write to `## Status`, `.task-id` or `review/*` is still denied or prompted, or that `mark-approved` remains the only route to APPROVED.

Fix: add negative criteria for each trusted file, with a test that asserts the resulting rules for those paths.

**Important**

**"A background builder ticks a SPEC.md checkbox and appends to PROGRESS.md with no prompt."** — The only test is `install.sh`, which checks the merged settings and never exercises a builder.

The criterion is a runtime behaviour, and it depends on rule precedence (deny > ask > allow), on `~` expansion in the rule paths, and on any other ask or deny rules left in user or project settings. A settings-file diff does not show that no prompt appears. Bash redirects such as `sed -i` or `>` are also not covered by `Edit`/`Write` rules.

Fix: restate the criterion as a checkable property of the merged settings, such as no remaining ask or deny rule matching those paths, or add a real permission-evaluation check.

**"Uninstall removes exactly the entries install added."** — The criterion is ambiguous in three cases.

- The user already had an identical entry such as `~/.agent/tasks` in `additionalDirectories`. Uninstall would remove an entry install did not add.
- The old SPEC.md ask rule was removed on install. It is unclear whether uninstall restores it.
- Repeated installs are not addressed.

Fix: state the ownership, idempotency and ask-rule restore behaviour, and add a fixture row for each.

**Tasks** — Task 2 ("add fixture rows") names no cases, so the criteria do not map to tasks.

Uninstall, removal of the ask rule, idempotency and the gate-file negatives have no named rows.

Fix: list the specific fixture cases tied to each criterion.

**Unverified** — I did not open `merge_claude_settings.py`, `install.sh` or the current ask rule. Claims about how the merge handles ownership and about the existing rule's exact form are unchecked. The originating issue was not available.

Verdict: 4 finding(s), 3 unverified (merge_claude_settings.py ownership behaviour, existing ask rule, originating issue)