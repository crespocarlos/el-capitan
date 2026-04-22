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
  bin/          ← shell scripts, Python utilities, GraphQL queries (symlinked to ~/.agent/bin/)
install.sh      ← creates symlinks from ~/.cursor/, ~/.claude/, ~/.agent/ → this repo
```

## Symlink rules

`.cursor/agents/` and `.cursor/skills/` are the canonical sources. `.claude/agents/` and `.claude/skills/` are symlinks pointing to them — edit only the `.cursor/` paths (symlinks follow automatically).

```bash
# Verify symlinks
ls -la .claude/agents   # should show → ../.cursor/agents
ls -la .claude/skills   # should show → ../.cursor/skills
```

## Editing conventions

- **Agent files** (`.cursor/agents/*.md`) — YAML frontmatter (`name`, `description`, `model`, `readonly`, `tools`, `maxTurns`) followed by protocol prose. Follow the existing style in the file you're editing.
- **Skill files** (`.cursor/skills/<name>/SKILL.md`) — workflow header, execution model, numbered steps. Follow `crew-commit/SKILL.md` as the canonical example.
- **Routing** — `crew-router.mdc` is the single source of truth. `.claude/CLAUDE.md` says "do not duplicate it here" — do not add routing entries to CLAUDE.md.
- **Templates** (`.agent/_*_TEMPLATE.md`) — pipeline-level templates read by multiple agents. Changes affect all future specs/runbooks/journal entries.
- **Tool budget in explorers** — `specwriter-explorer.md` and `tester-explorer.md` each have a hard ≤8 tool call budget. If you add a new discovery step that consumes a slot, update the budget breakdown comment.

## Verification pattern

Changes to agent/skill files are verified by reading them and checking the acceptance criteria in the SPEC.md. Most checks are `grep`-based:

```bash
grep "keyword" .cursor/agents/target-file.md   # presence check
diff .cursor/skills/crew-test/SKILL.md .claude/skills/crew-test/SKILL.md  # identity check
grep METRIC: .cursor/rules/crew-orchestrator.mdc .cursor/skills/crew-implement/SKILL.md  # METRIC audit docs + implement hooks
mkdir -p /tmp/el-capitan-metric-selftest && test -x .agent/bin/log-metric.py && python3 .agent/bin/log-metric.py /tmp/el-capitan-metric-selftest selftest=1
python3 -m py_compile .agent/bin/task-bundle.py
grep -E "task-bundle|bundle-manifest" AGENTS.md .agent/bin/task-bundle.py
```

There is no lint, typecheck, or unit test to run.
