**Critical: Acceptance criteria, "Install adds `Edit(~/.agent/tasks/**)` and `Write(~/.agent/tasks/**)` to the allow list"** — The allow rule covers the whole task directory, including the files the Summary says the gates trust.

A background builder, or a prompt-injected one, can use Write to change `## Status` in SPEC.md to APPROVED. It can also rewrite `.task-id`, or forge `review/*.expect` nonces and saved replies. That bypasses Gate 1 (the owner running `crew-task.py mark-approved`) and the review evidence, with no prompt. The ask rule being removed was the only guard. The Summary names these assets and then no criterion protects them.

Fix: Scope the allow to the files builders need (PROGRESS.md, REPORT.md, SPEC.md checkboxes). Add deny or ask rules for `.task-id` and `review/**`, and a rule for the Status line. Or put the choice under `## Open questions` as `[NEEDS CLARIFICATION: how are Status, .task-id and review/ kept owner-only?]`.

**Important: Acceptance criteria, "removes the old ask rule for task SPEC.md files"** — The criterion removes the only protection on SPEC.md and has no negative counterpart.

A literal build deletes the ask rule and leaves nothing that stops a SPEC.md write that flips `## Status`. No criterion fails if a builder can write APPROVED. The spec needs a "must stay impossible" criterion: a background builder cannot change `## Status`, `.task-id` or `review/*` without a prompt or a block.

Fix: Add a criterion that a write to those paths still prompts or is denied, and state that deny and ask rules take precedence over the new allow.

**Important: Acceptance criteria, "Uninstall removes exactly the entries install added"** — The criterion is ambiguous for entries that already existed.

If the user already had `~/.agent/tasks` in `additionalDirectories`, or the same allow rule, uninstall deletes the user's own entry. The old ask rule, removed on install, is not restored on uninstall. Re-installing over an existing settings file is also unspecified.

Fix: Add criteria for idempotent install, for preserving pre-existing identical entries on uninstall, and for whether uninstall restores the ask rule.

**Important: Summary, "every write under `~/.agent/tasks` ... prompts today"** — The spec does not verify its premise or the mechanism.

The spec never says whether the prompt comes from the ask rule or from the directory being outside the working directories. It also doesn't say whether `~` and `**` expand in the settings file as the spec assumes. If the prompt comes from the ask rule or from another hook, the change may still stall builders.

Fix: State the source of the prompt, and make the second criterion cover the case where a hook or an existing deny rule still blocks the write.

Verdict: 4 finding(s), 4 unverified (merge_claude_settings.py behavior, the existing ask rule's text, hooks guarding the task dir, `~` expansion in permission rules)