**Critical — Acceptance criteria, first bullet: "Install adds `Edit(~/.agent/tasks/**)` and `Write(~/.agent/tasks/**)` to the allow list"**

The Summary says the task directory holds what the gates trust: the `## Status` line, `.task-id` and the `review/*.expect` nonces. A blanket allow on `**` lets any background builder write all of them with no prompt. A builder could set Status to APPROVED, skipping Gate 1 (the owner's `mark-approved`). It could also rewrite `.task-id` or forge review evidence. The old ask rule on SPEC.md was the only guard on the Status line, and the spec removes it.

Fix: scope the allow to the files builders need (PROGRESS.md, REPORT.md, and checkbox edits only), keep a deny or ask rule for Status, `.task-id` and `review/**`, and add a criterion that a builder write to each of those still prompts or is denied.

**Critical — Acceptance criteria, first bullet: "removes the old ask rule for task SPEC.md files"**

Checkbox ticks in SPEC.md and edits to its Status line go through the same Edit tool on the same file. Permission rules match paths, not line content, so the spec can't allow one without allowing the other. Removing the ask rule therefore gives up the gate. The spec doesn't say what replaces it, for example a hook that rejects Status changes outside `crew-task.py`.

Fix: add a criterion that says how Status changes stay owner-only once the ask rule is gone, or put the mechanism under `## Open questions` as `[NEEDS CLARIFICATION: …]`.

**Important — Acceptance criteria, first bullet: "`~/.agent/tasks` to `additionalDirectories`"**

The spec doesn't say whether deny rules, or rules in the user's own settings, still take precedence over the new allow. It also doesn't say what happens when the user already has the entry or a conflicting rule. If the user had `~/.agent/tasks` in `additionalDirectories` before install, uninstall removes it, which breaks their setup.

Fix: add criteria that install is idempotent and that uninstall leaves pre-existing user entries and deny rules intact.

**Important — Acceptance criteria, third bullet: "Uninstall removes exactly the entries install added"**

There is no stated way to tell which entries install added versus which the user already had. The old ask rule that install removes is also never restored on uninstall. A literal build that deletes the allow entries by value is fine for a fresh install and destructive otherwise.

Fix: state whether uninstall restores the ask rule, and how entries the user already had are preserved.

**Consider — Acceptance criteria, second bullet: "with no prompt"**

Tilde expansion and path matching can differ when `~/.agent/tasks` is a symlink or the home path is not canonical. The rule might then not match, and the builder would still stall. This only costs one more fixture case.

Verdict: 4 finding(s), 1 unverified. I did not read the repo, so I did not verify the actual rule syntax in `merge_claude_settings.py`, how existing rules are matched, or whether a hook already guards Status.