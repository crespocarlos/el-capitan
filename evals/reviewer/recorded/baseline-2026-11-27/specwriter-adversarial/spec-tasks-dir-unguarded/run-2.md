**Critical**

**"every write under `~/.agent/tasks` (PROGRESS.md, REPORT.md, checkbox ticks in SPEC.md) prompts today, so builders stall."** — The approach contradicts the spec's own second paragraph.

The second paragraph says the directory holds what the gates trust: the `## Status` line, `.task-id` and `review/*.expect` nonces. `Edit(~/.agent/tasks/**)` and `Write(~/.agent/tasks/**)` let an unattended builder do three things. It can move Status to APPROVED itself, which bypasses Gate 1 and `mark-approved`. It can rewrite `.task-id`. It can forge or overwrite review evidence. The old ask rule on SPEC.md was probably the only human checkpoint, and the change removes it. The complaint was that builder writes to PROGRESS.md, REPORT.md and checkboxes stall, and the fix opens far more than that.

Fix: scope the allow to the files builders legitimately write, and keep the ask or deny on Status, `.task-id` and `review/**`. If that cannot be expressed in permission globs, put the question under `## Open questions` as `[NEEDS CLARIFICATION: how are SPEC.md checkbox ticks allowed without allowing Status edits?]`.

**Important**

**Acceptance criteria (all three)** — No criterion protects the gate-trusted files.

Nothing says a builder write to the Status line, `.task-id` or `review/` must still be blocked or prompted. Nothing says `mark-approved` remains the only route to APPROVED. The criteria would pass while Gate 1 is defeated.

Fix: add negative criteria, for example "a background builder's write to `.task-id` or `review/*.expect` is still denied or prompted", and test them.

**"A background builder ticks a SPEC.md checkbox and appends to PROGRESS.md with no prompt."** — Nothing proves this end to end.

The only test is `install.sh`, which checks the settings file contents. It does not show a permission decision for a real path. Whether a path-glob rule overrides the existing ask rule, and how `~` expands, is unverified.

Fix: add a test that evaluates the resulting rules against concrete paths, covering both allowed and still-guarded files, or state the assumption about rule precedence.

**"Uninstall removes exactly the entries install added."** — The criterion is untestable as written, and the Tests section has no uninstall case.

There is no coverage of three cases:
- The user already had one of these entries before install.
- Install runs twice, so idempotency is in question.
- The old ask rule is removed on install, so uninstall must either restore it or deliberately not restore it.

Fix: specify the pre-existing-entry and restore behavior, and add fixture rows for them.

**Consider**

**"`~/.agent/tasks` to `additionalDirectories`"** — This grants more than write access. Adding the directory to `additionalDirectories` also grants read access for every session, including non-crew ones. Whether that is intended is unstated.

Fix: state it as intended, or scope it.

Verdict: 4 finding(s), 3 unverified: the permission rule precedence of allow vs ask, the existing contents of `merge_claude_settings.py` and `install.sh`, and whether `crew-task.py` independently validates Status.