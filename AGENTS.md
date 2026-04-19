# el-capitan — Agent Guide

This repo is the el-capitan agentic pipeline system itself. All files are markdown, shell scripts, and Python utilities — there is no build step and no package manager.

## Bootstrap

No setup required. Skip the bootstrap step in any worktree.

```bash
# Nothing to run — no node_modules, no Cargo.toml, no pyproject.toml
```

## Tests

No automated test runner is configured. `crew test` will return WARN with no test command.

Verification: run **`crew test`** (typed `## Tests` + optional scriptable `runbook.md`) and check **Acceptance Criteria** / per-task **Acceptance** in SPEC.md — not a `### Manual` block under `## Tests` (removed from the template).

Legacy one-line `## Status: <value>` specs remain supported by Status readers; new specs use the two-line `## Status\n<value>` form.

## File layout

```
.cursor/
  rules/        ← always-loaded orchestration rules (.mdc, alwaysApply: true)
  agents/       ← agent protocols (.md) — symlinked from .claude/agents/
  skills/       ← inline skill protocols — symlinked from .claude/skills/
.claude/
  CLAUDE.md     ← Claude Code session instructions (symlinked to ~/.claude/CLAUDE.md)
  agents/       ← canonical agent source files
  skills/       ← canonical skill source files
  hooks/        ← PostToolUse, Notification, SessionStart hooks
.agent/
  _SPEC_TEMPLATE.md
  _BUG_SPEC_TEMPLATE.md
  _RUNBOOK_TEMPLATE.md
  _JOURNAL_TEMPLATE.md
  tools/        ← shell + Python utilities (symlinked to ~/.agent/tools/)
  scripts/      ← fallback dispatch scripts
  queries/      ← GraphQL query files
install.sh      ← creates symlinks from ~/.cursor/, ~/.claude/, ~/.agent/ → this repo
```

## Symlink rules

`.claude/agents/` is the canonical source. `.cursor/agents/` is a symlink to it — edit only the `.cursor/` path (the symlink follows automatically). Same for `.claude/skills/` ↔ `.cursor/skills/`.

```bash
# Verify symlinks
ls -la .cursor/agents   # should show → ../.claude/agents
ls -la .cursor/skills   # should show → ../.claude/skills
```

## Editing conventions

- **Agent files** (`.cursor/agents/*.md`) — YAML frontmatter (`name`, `description`, `model`, `readonly`, `tools`, `maxTurns`) followed by protocol prose. Follow the existing style in the file you're editing.
- **Skill files** (`.cursor/skills/<name>/SKILL.md`) — workflow header, execution model, numbered steps. Follow `crew-diff/SKILL.md` as the canonical example.
- **Routing** — `crew-router.mdc` is the single source of truth. `.claude/CLAUDE.md` says "do not duplicate it here" — do not add routing entries to CLAUDE.md.
- **Templates** (`.agent/_*_TEMPLATE.md`) — pipeline-level templates read by multiple agents. Changes affect all future specs/runbooks/journal entries.
- **Tool budget in explorers** — `specwriter-explorer.md` and `tester-explorer.md` each have a hard ≤8 tool call budget. If you add a new discovery step that consumes a slot, update the budget breakdown comment.

## Verification pattern

Changes to agent/skill files are verified by reading them and checking the acceptance criteria in the SPEC.md. Most checks are `grep`-based:

```bash
grep "keyword" .cursor/agents/target-file.md   # presence check
diff .cursor/skills/crew-test/SKILL.md .claude/skills/crew-test/SKILL.md  # identity check
```

There is no lint, typecheck, or unit test to run.
