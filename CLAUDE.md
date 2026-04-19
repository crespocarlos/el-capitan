# el-capitan — Claude Code Project Context

You are editing the el-capitan pipeline system itself — the agents, skills, and orchestration rules that power the crew commands. This is different from running crew commands in another repo.

## What this repo is

El-capitan is a spec-driven agentic engineering pipeline. It contains:
- **Orchestration rules** — `.cursor/rules/crew-orchestrator.mdc`, `crew-router.mdc` (always loaded)
- **Agent protocols** — `.cursor/agents/crew-*.md`, `specwriter-*.md`, `reviewer-*.md`, `tester-*.md`
- **Skill files** — `.cursor/skills/<name>/SKILL.md`
- **Pipeline templates** — `.agent/_SPEC_TEMPLATE.md`, `_BUG_SPEC_TEMPLATE.md`, `_RUNBOOK_TEMPLATE.md`
- **Tools** — `.agent/tools/` (shell scripts, Python utilities)

The pipeline routing instructions for using crew commands are in `.claude/CLAUDE.md` (loaded globally from `~/.claude/CLAUDE.md`). This file is for project-specific context when editing el-capitan itself.

## Key invariants for self-referential edits

- **Routing table** — `crew-router.mdc` is the single source of truth. `.claude/CLAUDE.md` explicitly says not to duplicate routing entries there.
- **Symlinks** — `.cursor/agents/` and `.cursor/skills/` are symlinks to `.claude/agents/` and `.claude/skills/`. Edit `.cursor/` paths only; the symlink propagates changes. Do not create files under `.claude/agents/` or `.claude/skills/` directly.
- **No build, no tests** — this repo has no package manager, no test runner, no type-checker. Verification is grep-based acceptance checks against the edited files.
- **`.claude/skills` is a directory symlink to `.cursor/skills`** — files like `.claude/skills/crew-test/SKILL.md` and `.claude/skills/crew-open-pr/references/pr-template.md` auto-mirror via the directory symlink, so editing the `.cursor/skills/...` path propagates automatically. No manual byte-identical sync is needed.
- **Pipeline-level templates** live in `.agent/` and are read by multiple agents. Changes affect all future specs and runbooks.
- **Tool budgets** — explorer subagents (`specwriter-explorer.md`, `tester-explorer.md`) have hard ≤8 call budgets. If adding a discovery step that consumes a slot, update the budget breakdown comment in the file.

## When using crew commands on this repo

You can use crew commands to improve el-capitan itself. The pipeline is self-applicable:

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
| `.cursor/agents/crew-specwriter.md` | Spec drafting protocol (Steps 1-6) |
| `.cursor/agents/crew-builder.md` | Implementation protocol + Completion Protocol |
| `.cursor/agents/specwriter-explorer.md` | Codebase exploration for spec writing |
| `.cursor/agents/tester-explorer.md` | Test file and convention discovery |
| `.cursor/skills/crew-test/SKILL.md` | Test runner skill |
| `.agent/_SPEC_TEMPLATE.md` | Standard spec template |
| `.agent/_BUG_SPEC_TEMPLATE.md` | Bug spec template |
| `.agent/_RUNBOOK_TEMPLATE.md` | Validation runbook template |
| `.agent/.ralph-instructions-template` | Ralph loop instructions (keep in sync with crew-builder.md Completion Protocol) |
