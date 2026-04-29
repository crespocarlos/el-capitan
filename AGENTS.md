# el-capitan — Agent Guide

El-capitan is a spec-driven agentic engineering pipeline. All files are markdown, shell scripts, and Python utilities — there is no build step and no package manager. It contains:

- **Orchestration rules** — `.cursor/rules/crew-orchestrator.mdc`, `crew-router.mdc` (always loaded)
- **Agent protocols** — `.cursor/agents/crew-*.md`, `specwriter-*.md`, `reviewer-*.md`, `tester-*.md`
- **Skill files** — `.cursor/skills/<name>/SKILL.md`
- **Pipeline templates** — `.agent/_SPEC_TEMPLATE.md`, `_BUG_SPEC_TEMPLATE.md`, `_RUNBOOK_TEMPLATE.md`
- **Tools** — `.agent/bin/` (shell scripts, Python utilities, GraphQL queries)

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
  rules/
    crew-orchestrator.mdc       ← pipeline state machine, autopilot logic
    crew-router.mdc             ← command routing table (single source of truth)
    crew-explorer-conventions.mdc ← shared conventions for explorer subagents
    personal.mdc                ← personal preferences (alwaysApply)
  agents/       ← canonical agent source files (15 agents)
  skills/       ← canonical skill source files (9 skills)
.claude/
  CLAUDE.md     ← Claude Code project context (references @AGENTS.md)
  agents/       ← symlink → ../.cursor/agents
  skills/       ← symlink → ../.cursor/skills
  hooks/        ← PostToolUse, Notification, SessionStart hooks
.agent/
  _SPEC_TEMPLATE.md
  _BUG_SPEC_TEMPLATE.md
  _RUNBOOK_TEMPLATE.md
  _JOURNAL_TEMPLATE.md
  .ralph-instructions-template  ← Ralph loop instructions (keep in sync with crew-builder.md)
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

## Using crew commands on this repo

The pipeline is self-applicable — you can use crew commands to improve el-capitan itself:

```
crew spec "add X feature to the pipeline"   # draft a spec for a pipeline improvement
crew implement                               # implement it in a worktree
crew test                                   # will return WARN (no test runner) — use manual checklist
```

The worktree will be created at `~/worktrees/el-capitan-<branch>/`. No bootstrap is needed.

## Files you will commonly edit

| File | What it controls |
|---|---|
| `.cursor/rules/crew-router.mdc` | Command routing and subagent dispatch table |
| `.cursor/rules/crew-orchestrator.mdc` | Pipeline state machine, autopilot logic |
| `.cursor/rules/crew-explorer-conventions.mdc` | Shared conventions for explorer subagents |
| `.cursor/agents/crew-specwriter.md` | Spec drafting protocol (Steps 1-6) |
| `.cursor/agents/crew-builder.md` | Implementation protocol + Completion Protocol |
| `.cursor/agents/crew-reviewer.md` | Multi-lens review orchestration |
| `.cursor/agents/specwriter-explorer.md` | Codebase exploration for spec writing |
| `.cursor/agents/specwriter-scope.md` | Scope and implementer critic for spec writing |
| `.cursor/agents/tester-explorer.md` | Test file and convention discovery |
| `.cursor/skills/crew-test/SKILL.md` | Test runner skill |
| `.agent/_SPEC_TEMPLATE.md` | Standard spec template |
| `.agent/_BUG_SPEC_TEMPLATE.md` | Bug spec template |
| `.agent/_RUNBOOK_TEMPLATE.md` | Validation runbook template |
| `.agent/.ralph-instructions-template` | Ralph loop instructions (keep in sync with crew-builder.md Completion Protocol) |

## Verification pattern

Changes to agent/skill files are verified by reading them and checking the acceptance criteria in the SPEC.md. Most checks are `grep`-based:

```bash
grep "keyword" .cursor/agents/target-file.md   # presence check
grep METRIC: .cursor/rules/crew-orchestrator.mdc .cursor/skills/crew-implement/SKILL.md  # METRIC audit docs + implement hooks
mkdir -p /tmp/el-capitan-metric-selftest && test -x .agent/bin/log-metric.py && python3 .agent/bin/log-metric.py /tmp/el-capitan-metric-selftest selftest=1
python3 -m py_compile .agent/bin/task-bundle.py
grep -E "task-bundle|bundle-manifest" AGENTS.md .agent/bin/task-bundle.py
```

There is no lint, typecheck, or unit test to run.
