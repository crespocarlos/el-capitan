# el-capitan — Agent Guide

El-capitan is a spec-driven agentic engineering pipeline. All files are markdown, shell scripts, and
Python utilities — there is no build step and no package manager. It contains:

- **Orchestration rules** — `rules/crew-orchestrator.mdc`, `crew-router.mdc` (always loaded)
- **Agent protocols** — `.cursor/agents/crew-*.md`, `specwriter-*.md`, `reviewer-*.md`,
  `tester-*.md`
- **Skill files** — `.cursor/skills/<name>/SKILL.md`
- **Pipeline templates** — `.agent/_SPEC_TEMPLATE.md`, `_BUG_SPEC_TEMPLATE.md` (symlinks to the
  portable `spec-writing` skill's `references/`)
- **Tools** — `.agent/tools/` (CLIs, cataloged in `TOOLS.md` / `tools.json`); `.agent/scripts/`
  (source-only and internal helpers). Both install flat into `~/.agent/bin/`.

## Bootstrap

No setup required. Skip the bootstrap step in any worktree.

```bash
# Nothing to run — no node_modules, no Cargo.toml, no pyproject.toml
```

## Tests

Four hermetic checks, also run in CI (`.github/workflows/validate.yml`):

```bash
python3 .agent/tools/crew-lint.py --budget          # conventions, catalog, references, token budget
bash .claude/hooks/fixtures/run.sh                  # guard hooks, crew-ls gates, status reconcile
python3 evals/memory/run.py                         # memory retrieval and scope isolation
python3 evals/reviewer/test_review_findings.py      # review-findings normalize/persist/select
```

`crew test` looks for typed `## Tests` commands in a spec; with none it returns WARN. Verification of
a change means the four commands above plus the **Acceptance criteria** in SPEC.md. Specs use the
two-line `## Status\n<value>` form.

## File layout

```
.cursor/
  rules/
    crew-orchestrator.mdc       ← pipeline state machine, autopilot logic
    crew-router.mdc             ← command routing table (single source of truth)
    crew-explorer-conventions.mdc ← shared conventions for explorer subagents
    personal.mdc                ← personal preferences (alwaysApply)
  agents/       ← canonical agent source files (14 agents)
  skills/       ← canonical skill source files (17 skills, incl. portable spec-writing)
.claude/
  CLAUDE.md     ← Claude Code project context (references @AGENTS.md)
  agents/       ← symlink → ../.cursor/agents
  skills/       ← symlink → ../.cursor/skills
  hooks/        ← PostToolUse, Notification, SessionStart hooks
.agent/
  _SPEC_TEMPLATE.md      ← symlink → ../.cursor/skills/spec-writing/references/spec-template.md
  _BUG_SPEC_TEMPLATE.md  ← symlink → ../.cursor/skills/spec-writing/references/bug-spec-template.md
  _JOURNAL_TEMPLATE.md
  bin/          ← shell scripts, Python utilities, GraphQL queries (symlinked to ~/.agent/bin/)
install.sh      ← creates symlinks from ~/.cursor/, ~/.claude/, ~/.agent/ → this repo
```

## Symlink rules

`.cursor/agents/` and `.cursor/skills/` are the canonical sources. `.claude/agents/` and
`.claude/skills/` are symlinks pointing to them — edit only the `.cursor/` paths (symlinks follow
automatically).

```bash
# Verify symlinks
ls -la .claude/agents   # should show → ../.cursor/agents
ls -la .claude/skills   # should show → ../.cursor/skills
```

## Editing conventions

- **Agent files** (`.cursor/agents/*.md`) — YAML frontmatter (`name`, `description`, optional
  `readonly`, `tools`, `maxTurns`) followed by protocol prose. The harnesses read different subsets:
  Cursor reads `name`, `description`, `model`, `readonly`, `is_background` and ignores `tools` and
  `maxTurns`, inheriting every parent tool instead, so `readonly: true` is Cursor's only tool
  restriction; Claude Code reads `tools` and `maxTurns` and ignores `readonly`. `tools` therefore speaks
  Claude Code's ids (`Read`, `Grep`, `Glob`, `Bash`, `Agent`, …), and each frontmatter states which
  harness reads each key. `crew-lint` resolves every `mcp__<server>__<tool>` reference and every bare
  `tools:` id against the `mcp_servers` and `native_tools` allowlists in `.agent/tools/tools.json`, so
  register a new server or tool id there in the same change, and never put an id like that in prose.
  Do not set `model:`; see `rules/crew-router.mdc` for the model-inheritance rule. Follow the existing
  style in the file you're editing.
- **Skill files** (`.cursor/skills/<name>/SKILL.md`) — workflow header, execution model, numbered
  steps. Follow `crew-commit/SKILL.md` as the canonical example.
- **Routing** — `crew-router.mdc` is the single source of truth. `.claude/CLAUDE.md` says "do not
  duplicate it here" — do not add routing entries to CLAUDE.md.
- **Templates** — spec templates live in `.cursor/skills/spec-writing/references/` (edit there;
  `.agent/_*SPEC_TEMPLATE.md` are symlinks). Changes affect all future specs.
- **Tool budget in explorers** — `specwriter-explorer.md` and `tester-explorer.md` each declare a
  ≤8 tool call budget in prose and set `maxTurns: 8`. The prose is guidance, not an enforced cap: Cursor
  ignores `maxTurns`, and Claude Code enforces it as a turn limit (not a call limit). If you add a new
  discovery step that consumes a slot, update the budget breakdown comment.

## Using crew commands on this repo

The pipeline is self-applicable — you can use crew commands to improve el-capitan itself:

```
crew spec "add X feature to the pipeline"   # draft a spec for a pipeline improvement
crew implement                               # implement it in a worktree
crew test                                   # will return WARN (no test runner) — verify acceptance criteria
```

The worktree will be created at `~/worktrees/el-capitan-<branch>/`. No bootstrap is needed.

## Files you will commonly edit

| File | What it controls |
|---|---|
| `rules/crew-router.mdc` | Command routing and subagent dispatch table |
| `rules/crew-orchestrator.mdc` | Pipeline state machine, autopilot logic |
| `rules/crew-explorer-conventions.mdc` | Shared conventions for explorer subagents |
| `.cursor/agents/crew-specwriter.md` | Spec drafting protocol (Steps 1-6) |
| `.cursor/agents/crew-builder.md` | Implementation protocol + Completion Protocol |
| `.cursor/agents/crew-reviewer.md` | Multi-lens review orchestration |
| `.cursor/agents/specwriter-explorer.md` | Codebase exploration for spec writing |
| `.cursor/agents/specwriter-scope.md` | Scope and implementer critic for spec writing |
| `.cursor/agents/tester-explorer.md` | Test file and convention discovery |
| `.cursor/skills/crew-test/SKILL.md` | Test runner skill |
| `.cursor/skills/spec-writing/SKILL.md` | Portable spec-writing procedure (used by crew-specwriter) |
| `.cursor/skills/spec-writing/references/spec-template.md` | Standard spec template |
| `.cursor/skills/spec-writing/references/bug-spec-template.md` | Bug spec template |

## Verification pattern

Changes to agent/skill files are verified by reading them and checking the acceptance criteria in
the SPEC.md. Most checks are `grep`-based:

```bash
grep "keyword" .cursor/agents/target-file.md   # presence check
python3 .agent/tools/crew-lint.py --budget   # routing, catalog, reference integrity, token budget
bash .claude/hooks/fixtures/run.sh   # hook guards, crew-ls gates, status reconciliation
python3 evals/memory/run.py   # memory retrieval, scope isolation, conflict handling
python3 evals/reviewer/test_review_findings.py   # review-findings normalize/persist/select
```

All four are hermetic (no network, no API key) and run in CI via `.github/workflows/validate.yml`.
`evals/run.py` and `evals/reviewer/run.py` make model calls and need an API key; they are not part of
the deterministic gate.

## Persistent memory

`mem.py` manages typed, repo-scoped Markdown memories in `~/.agent/memory`; SQLite FTS5 is a
rebuildable index, not the source of truth. Run `bash install.sh` once to initialize the store and
install harness-neutral read instructions. Agents retrieve memory automatically. Repository scope
uses the upstream repository's bare name when available, so forks and upstream worktrees share their
memory.

Journal entries are immutable `observation` evidence in the same store. `mem.py search` and ranked
`mem.py context` (plan, implement, review, debug) include them; the unranked `--mode session`
listing excludes them unless `--include-observations` is passed. Import legacy journals read-only
with `mem.py journal import`.

Use `crew remember: <lesson>` only for durable, non-derivable information; use `crew memory seed` to
draft journal candidates for approval, and `crew memory doctor` to diagnose the store. `mem.py
ingest --source claude|codex --path <directory>` imports external memory read-only and never
reconfigures or edits its source repository. Verify with `python3 evals/memory/run.py` and `python3
.agent/tools/crew-lint.py`.
