# el-capitan — Agent Guide

Spec-driven agentic engineering pipeline. Markdown, shell, and Python only — no build step, no
package manager.

## Bootstrap

None. Skip the bootstrap step in any worktree; there is nothing to install or build.

## Tests

Hermetic suites, also run in CI (`.github/workflows/validate.yml`). Verification of a change means
those plus the **Acceptance criteria** in SPEC.md. Which suites cover what, and which need a full
permission run: `src/crew/AGENTS.md`.

## Layout

| Path | Contents |
|---|---|
| `rules/` | Always-loaded rules; `crew-router.mdc` is the routing source of truth |
| `.cursor/agents/`, `.cursor/skills/` | Canonical agent and skill sources — edit only here |
| `.claude/` | `CLAUDE.md`, guard hooks, and the `.cursor/skills` link; no agents link (install renders them) |
| `src/crew/` | Every command and module; catalog in `tools.json`, prose in `TOOLS.md` |
| `.agent/_*TEMPLATE.md` | Spec and journal templates, symlinked from skill `references/` |
| `evals/` | Hermetic suites, one file per tool or family |
| `tui/` | Dashboard over `crew ls` data (Textual, a dev dependency); `s` runs a confirmed `crew-task.py` move, nothing else writes; not catalogued or installed |
| `install.sh` | Links `~/.cursor/`, `~/.claude/`, `~/.agent/bin/` from the catalog |

Tool-tree layout, module naming, exit codes, output contracts, and the glossary:
`src/crew/AGENTS.md`.

## Editing

Use the edit or write tool for every text change. A `python3 - <<'PY'`, `sed -i`, `tee`, or a
redirect that rewrites a tracked file bypasses the edit log and the review diff, and turns a wrong
anchor into a silent no-op; shell heredocs are for scratch artifacts and task-directory writes only.

- **Prompt files** — load the `prompt-authoring` skill first.
  Frontmatter, the tool-id registry, the size ceiling, and the `references/` rule:
  `src/crew/AGENTS.md` → Authoring agent and skill files. `crew-lint` enforces all of it.
- **Prompt growth** — a change that adds rule or prompt text names what it replaces, or justifies the
  net growth in its PR body; `crew-lint --budget` prints the byte delta since the merge base with
  `origin/main`, and fails a file above 90% of its ceiling.
- **Routing and state** — `crew-router.mdc` routes; `crew-orchestrator.mdc` owns the state machine
  and autopilot rules.
- **Templates** — edit `.cursor/skills/spec-writing/references/`; `.agent/_*SPEC_TEMPLATE.md` are
  symlinks, so a change affects every future spec.
- **Guards are hooks, not prose** — a rule that must hold every time lives in `.claude/hooks/`,
  registered in both hook configs with an allow and a deny case in `evals/tools/hook_cases.py`.
- **Reviewer personas** — the procedure is
  [persona authoring](.cursor/agents/crew-reviewer/references/persona-authoring.md).

The pipeline improves itself through its own `crew` commands. Persistent memory (`crew-mem.py`):
`src/crew/AGENTS.md`.
