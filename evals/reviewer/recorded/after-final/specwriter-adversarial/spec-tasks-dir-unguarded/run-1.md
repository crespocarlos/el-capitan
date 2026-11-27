**Criterion 1 (`Edit(~/.agent/tasks/**)` and `Write(~/.agent/tasks/**)` in the allow list)** — The blanket allow lets a background builder write the files the gates trust.

The Summary lists the `## Status` line, `.task-id` and `review/*.expect` nonces as gate-trusted. With `Edit` and `Write` on `**`, a builder can change `## Status` to APPROVED itself and skip Gate 1, which belongs to the owner via `crew-task.py mark-approved`. It can also forge `.task-id` or the review nonces and saved replies. Removing the old ask rule takes away the one prompt that guarded SPEC.md. The spec never says how Gate 1 or the review evidence stays protected, so a literal build gives the builder self-approval.

Fix: add criteria that the builder cannot write `## Status`, `.task-id` or `review/**` without a prompt (deny or ask rules that take precedence over the allow, or a hook). Also put under `## Open questions` how SPEC.md is scoped, since the allow rule can't separate a checkbox tick from a status edit.

**Criterion 2 ("ticks a SPEC.md checkbox and appends to PROGRESS.md with no prompt")** — Only the happy path is covered, and no criterion stays impossible.

No criterion says a builder edit to `## Status`, a write to `.task-id`, or a write to `review/*.expect` must still be blocked or prompt. A build that allows everything passes all three criteria.

Fix: add negative criteria for each gate-trusted file, naming the outcome that must stay impossible.

**Criterion 1 ("removes the old ask rule")** — Existing installs and unrelated user rules are not addressed.

The spec doesn't say what happens if the ask rule text differs, if the user already has their own `~/.agent/tasks` rule, or if install runs twice. Criterion 3's "exactly the entries install added" is ambiguous when a matching entry already existed before install. Uninstall could then delete the user's own rule, or fail to restore the removed ask rule.

Fix: add criteria for idempotent re-install, preserving pre-existing user entries on uninstall, and restoring or deliberately not restoring the ask rule.

**Criterion 2 (background builder, no prompt)** — It assumes the allow rule applies to background agents.

It assumes that allow rules and `additionalDirectories` are honored for background subagents and that no deny or ask rule elsewhere, such as project settings, overrides them. Nothing verifies this, and the criterion may pass in fixtures while builders still stall. Record it under `## Open questions` as `[NEEDS CLARIFICATION: do allow rules take effect for background builders, and does a project-level ask rule override them?]`.

Verdict: 3 finding(s) plus 1 assumption flagged, 4 unverified (I read no case files: the settings merge script, the fixtures, the existing ask rule, and the `crew-task.py` guards)