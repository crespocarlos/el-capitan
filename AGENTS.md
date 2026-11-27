# el-capitan — Agent Guide

Spec-driven agentic engineering pipeline. Markdown, shell, and Python only — no build step, no
package manager.

## Bootstrap

None. Skip the bootstrap step in any worktree; there is nothing to install or build.

## Tests

Hermetic suites, also run in CI (`.github/workflows/validate.yml`). Verification of a change means
those plus the **Acceptance criteria** in SPEC.md. Which suites cover what, and which need a full
permission run: `.agent/tools/AGENTS.md`. The builder's Completion Protocol runs a spec's typed
`## Tests` commands.

## Layout

| Path | Contents |
|---|---|
| `rules/` | Always-loaded rules; `crew-router.mdc` is the routing source of truth |
| `.cursor/agents/`, `.cursor/skills/` | Canonical agent and skill sources — edit only here |
| `.claude/` | `CLAUDE.md`, guard hooks, and the `.cursor/skills` link; no agents link (install renders them) |
| `.agent/tools/` | Every command and module; catalog in `tools.json`, prose in `TOOLS.md` |
| `.agent/_*TEMPLATE.md` | Spec and journal templates, symlinked from skill `references/` |
| `evals/` | Hermetic suites, one file per tool or family |
| `tui/` | Dashboard over `crew ls` data (Textual, a dev dependency); `s` runs a confirmed `crew-task.py` move, nothing else writes; not catalogued or installed |
| `install.sh` | Links `~/.cursor/`, `~/.claude/`, `~/.agent/bin/` from the catalog |

Tool-tree layout, module naming, exit codes, output contracts, and the glossary:
`.agent/tools/AGENTS.md`.

## Editing

Use the edit or write tool for every text change. A `python3 - <<'PY'`, `sed -i`, `tee`, or a
redirect that rewrites a tracked file bypasses the edit log and the review diff, and turns a wrong
anchor into a silent no-op; shell heredocs are for scratch artifacts and task-directory writes only.

- **Prompt files** — load the `prompt-authoring` skill first.
  Frontmatter, the tool-id registry, the size ceiling, and the `references/` rule:
  `.agent/tools/AGENTS.md` → Authoring agent and skill files. `crew-lint` enforces all of it.
- **Routing and state** — `crew-router.mdc` routes; `crew-orchestrator.mdc` owns the state machine
  and autopilot rules. Neither is duplicated in `.claude/CLAUDE.md`.
- **Templates** — edit `.cursor/skills/spec-writing/references/`; `.agent/_*SPEC_TEMPLATE.md` are
  symlinks, so a change affects every future spec.
- **Explorer budget** — `specwriter-explorer.md` declares 12 tool calls (the protocol and lookups reads
  included) and `maxTurns: 13` (one more for the report); update both when you add a discovery step.
- **Guards are hooks, not prose** — a rule that must hold every time lives in `.claude/hooks/`,
  registered in both hook configs with an allow and a deny case in `evals/tools/hook_cases.py`.
- **Reviewer personas** — the procedure is
  [persona authoring](.cursor/agents/crew-reviewer/references/persona-authoring.md).

## Self-application

The pipeline improves itself: `crew spec "add X to the pipeline"`, then `crew implement`, `crew
review`, `crew commit`.

## Persistent memory

`crew-mem.py` keeps typed, repo-scoped Markdown units in `~/.agent/memory` (SQLite FTS5 is a
rebuildable index), scoped by the upstream repository's bare name so forks and worktrees share it.
Code, docs, and user instructions win over it. Read contract:
`~/.cursor/skills/crew-memory/references/contract.md`.
