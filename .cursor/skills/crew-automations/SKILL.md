---
name: crew-automations
description: "Reference guide for setting up Cursor Automations with el-capitan crew members. Trigger: 'crew automations'."
---

# Cursor Automations

Reference guide for running crew members as Cursor Automations — event-driven agents that run in cloud sandboxes without the IDE open.

Configure at [cursor.com/automations](https://cursor.com/automations).

## When Invoked

Present this guide to the user. Help them choose which crew members to automate and in which mode (gated or automated). Do not create automations programmatically — this is a configuration reference.

## Cloud sandbox limitations

Automations run in ephemeral cloud sandboxes. Each run clones the repo fresh. This means:

- **No `~/.agent/`** — no journal, no PROFILE.md, no task state, no SPEC.md
- **No ralph** — not installed in the sandbox
- **No worktrees** — sandbox has one checkout
- **No local tools** — no `journal-search.py`, no `manage-worktree.sh`

Automations work best for **stateless** crew members that read the repo/PR and produce output.

## Gated mode

Automations assist but you make all decisions. Output is comments and suggestions — never merges, approvals, or direct commits.

### PR Review (gated)

```
Trigger:  GitHub → Pull request opened
Tools:    Comment on PR (approvals DISABLED)
Prompt:
  You are a code reviewer. Read the PR diff and the repo's
  .cursor/agents/crew-pr-reviewer.md for your review protocol.
  Follow it exactly. Post your review as a PR comment.
  For each finding, include the file path and line range.
  Never approve or request changes — comment only.
```

### Diff Analysis (gated)

```
Trigger:  GitHub → Pull request pushed
Tools:    Comment on PR (approvals DISABLED)
Prompt:
  Analyze the latest push to this PR. Check for:
  type safety issues, missing error handling, pattern
  violations vs the repo's conventions, and test gaps.
  Post a brief analysis as a PR comment. If everything
  looks clean, comment "LGTM — no issues found."
```

### Weekly Cleanup (gated)

```
Trigger:  Scheduled → weekly (Sunday 9am)
Tools:    Open pull request
Prompt:
  Scan the repo for: unused imports, dead code,
  TODO comments older than 30 days, deprecated API usage.
  If you find anything worth cleaning up, open a PR
  with the fixes. If nothing found, do nothing.
```

## Automated mode

Automations handle the full pipeline. Use with caution — less human oversight.

### PR Review (automated)

```
Trigger:  GitHub → Pull request opened
Tools:    Comment on PR (approvals ENABLED)
Prompt:
  You are a code reviewer. Read the PR diff and the repo's
  .cursor/agents/crew-pr-reviewer.md for your review protocol.
  Follow it exactly. Post your review as a PR comment.
  For each finding, include the file path and line range.
  If there are Critical findings, request changes.
  If there are only Consider items or no findings, approve.
```

### Auto-fix on Push (automated)

```
Trigger:  GitHub → Pull request pushed
Tools:    Comment on PR, Open pull request
Prompt:
  Analyze the latest push. If you find type errors,
  missing imports, or lint violations that have obvious
  fixes, push a fix commit directly. Comment what you
  fixed. If issues require judgment, comment only —
  don't guess at fixes.
```

### Spec from Issue (automated)

```
Trigger:  GitHub → Issue labeled "spec"
Tools:    Comment on PR
Prompt:
  Read the issue body. Draft a SPEC.md following the
  template in .agent/_SPEC_TEMPLATE.md. Post the spec
  as an issue comment. Add the label "spec-drafted"
  when done. Do not create branches or PRs.
  Note: you don't have access to journal-search or
  auto-recall — draft the spec from the issue and
  repo context only.
```

### Implement from Approved Spec (automated)

```
Trigger:  GitHub → Issue labeled "approved"
Tools:    Open pull request
Prompt:
  Read the issue body (which should contain a SPEC.md).
  Implement all tasks described in the spec. Run any
  acceptance checks mentioned. Open a PR with the
  implementation. Reference the issue in the PR body.
  Note: you don't have ralph or worktrees — implement
  directly in the sandbox checkout.
```

### Weekly Cleanup (automated)

```
Trigger:  Scheduled → weekly (Sunday 9am)
Tools:    Open pull request
Prompt:
  Scan the repo for: unused imports, dead code,
  TODO comments older than 30 days, deprecated API usage.
  If you find anything, open a PR with fixes and
  auto-merge if CI passes. If nothing found, do nothing.
```

## Choosing a mode

| Concern | Gated | Automated |
|---------|-------|-----------|
| Risk tolerance | Conservative | Comfortable with AI decisions |
| Review quality | You validate every suggestion | Agent acts on its own judgment |
| Speed | Slower (human in loop) | Faster (no waiting) |
| Best for | Critical repos, unfamiliar codebases | Personal projects, well-tested repos |

Start with **gated mode** for any new automation. Promote to automated after you trust the output quality over 10+ runs.

## Memories

Enable the **Memories** tool on any automation to let it learn across runs. The agent stores notes in a persistent `MEMORIES.md` that survives between runs. Useful for:

- Accumulating common review findings per repo
- Learning which files are frequently problematic
- Remembering repo-specific conventions it discovered

Memories are not shared with your local journal — they're automation-scoped.

## Rules

- This skill is a reference guide — it does not create or modify automations
- Always recommend gated mode as the starting point
- Call out cloud sandbox limitations for each automation
- Automations are configured at cursor.com/automations, not in the repo
