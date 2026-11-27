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
| `.claude/` | `CLAUDE.md`, guard hooks, and symlinks to `.cursor/agents` and `.cursor/skills` |
| `.agent/tools/` | Every command and module; catalog in `tools.json`, prose in `TOOLS.md` |
| `.agent/_*TEMPLATE.md` | Spec and journal templates, symlinked from skill `references/` |
| `evals/` | Hermetic suites, one file per tool or family |
| `install.sh` | Links `~/.cursor/`, `~/.claude/`, `~/.agent/bin/` from the catalog |

Tool-tree layout, module naming, exit codes, and output contracts: `.agent/tools/AGENTS.md`.

## Editing

Use the edit or write tool for every text change. A `python3 - <<'PY'`, `sed -i`, `tee`, or a
redirect that rewrites a tracked file bypasses the edit log and the review diff; shell heredocs are
for scratch artifacts and task-directory writes only.

- **Agent and skill files** — frontmatter then protocol prose. Per-key harness behavior, the tool-id
  registry, the 12,000-byte ceiling, and the `references/` rule: `.agent/tools/AGENTS.md` →
  Authoring agent and skill files. `crew-lint` enforces all of it.
- **Routing and state** — `crew-router.mdc` routes; `crew-orchestrator.mdc` owns the state machine
  and autopilot rules. Neither is duplicated in `.claude/CLAUDE.md`.
- **Templates** — edit `.cursor/skills/spec-writing/references/`; `.agent/_*SPEC_TEMPLATE.md` are
  symlinks, so a change affects every future spec.
- **Explorer budget** — `specwriter-explorer.md` declares ≤8 tool calls and
  `maxTurns: 8`; update the breakdown when you add a discovery step.
- **Guards are hooks, not prose** — a rule that must hold every time lives in `.claude/hooks/`,
  registered in both hook configs with an allow and a deny case in `evals/tools/hook_cases.py`. `crew-lint`
  fails an unregistered hook.
- **Reviewer personas** — four changes, two of them in code; the procedure is
  [persona authoring](.cursor/agents/crew-reviewer/references/persona-authoring.md).

## Self-application

The pipeline improves itself: `crew spec "add X to the pipeline"`, then `crew implement` (optional worktree;
default: a branch off main), `crew review`, `crew commit`.

## Persistent memory

`crew-mem.py` keeps typed, repo-scoped Markdown units in `~/.agent/memory`; SQLite FTS5 is a
rebuildable index, not the source of truth. Scope is the upstream repository's bare name, so forks and
worktrees share memory. Agents retrieve it automatically, and code, docs, and user instructions win
over it. Capture only durable, non-derivable lessons (`crew remember:`) and draft candidates with
`crew memory seed`. Read contract:
`~/.cursor/skills/crew-memory/references/contract.md`.
