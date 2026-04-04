# el-capitan

Route `crew <command>` triggers to the right crew member. If the message doesn't start with `crew`, respond normally — no routing.

## Routing

> Sync source: .cursor/rules/crew-router.mdc — that file is the single source of truth for the command list.

**Command list is in `crew-router.mdc`** — that file is the single source of truth. Do not duplicate it here.

File path convention:
- Orchestrator agents: `~/.claude/agents/crew-<name>.md` (e.g., `crew-reviewer.md`)
- Persona subagents: `~/.claude/agents/<orchestrator>-<persona>.md` (e.g., `reviewer-adversarial.md`)
- Skills: `~/.claude/skills/<name>/SKILL.md`

All agents and personas are registered as subagents at the top level of `~/.claude/agents/`. Personas have YAML frontmatter with `name`, `description`, `model`, `tools`, and `maxTurns`.

## How to invoke agents (CRITICAL)

**Orchestrator agents** (crew-reviewer, crew-specwriter, crew-thinker) run inline: read the agent file with `cat ~/.claude/agents/<name>.md` and follow its protocol directly. They dispatch persona subagents as part of their protocol.

**Persona subagents** (reviewer-adversarial, specwriter-scope, thinker-builder, etc.) are dispatched BY the orchestrator, not invoked directly. They are registered subagents that can be dispatched natively via the Agent tool — each gets its own context window.

Multi-persona dispatch priority:
1. **Agent tool** (native subagent dispatch) — preferred when available
2. **`claude -p` file-based dispatch** — parallel CLI processes as fallback
3. **Inline sequential** — run each persona's protocol one at a time (degraded, ordering bias)

`crew autopilot` and `crew status` are handled inline — see Pipeline section below.

**This routing is authoritative.** Read the file, follow its instructions. Do not override with judgment calls.

## Task state

```bash
REPO=$(basename $(git rev-parse --show-toplevel))
BRANCH=$(git branch --show-current)
BRANCH_DIR=~/.agent/tasks/$REPO/$BRANCH
```

Find active task: scan `$BRANCH_DIR/*/SPEC.md`, pick the non-done one. If multiple, present a choice. If none, fall back to `$BRANCH_DIR/SPEC.md`.

## Pipeline

```
spec → [Gate 1: approve spec] → implement → diff → commit → [Gate 2: approve message] → open PR → done
```

Two gates. Everything between auto-advances with `crew autopilot`.

**`crew autopilot`**: chains from current state to next gate. Not a mode toggle — means "advance from here." If a step fails, pauses and surfaces the error. No auto-retry.

**`crew status`**: prints current pipeline state derived from git/gh state. See crew-orchestrator.mdc for the full logic.

**`crew health`**: runs five health checks inline (symlinks, hooks, jq, gh auth, active SPEC.md). Auto-runs when `crew status` finds no active task.

**`crew abandon`**: gracefully abandons the current task — stashes changes, writes SESSION.md stub, appends ABANDONED to PROGRESS.md.

## PROGRESS.md

Append-only event log. Pipeline steps write `[YYYY-MM-DD HH:MM] TRANSITION: X → Y`. Never overwrite — only append. `crew status` reads git/gh, not this file. Use `cat PROGRESS.md` for the human-readable audit trail.

## Memory

Two memory systems. Keep them explicitly partitioned.

| System | What it stores | Horizon | How it's updated |
|--------|----------------|---------|-----------------|
| Journal (`~/.agent/journal/`) | Engineering decisions, what was built, what was learned, session outcomes | Long — weeks to months | Manually via `crew log` |
| Auto-memory (`~/.claude/projects/*/memory/`) | Behavioral corrections, style preferences, workflow patterns | Short — conversation to session | Auto-saved by Claude Code |

`crew log` is the only intended bridge: after writing a journal entry it may optionally promote a rule to auto-memory (saves as `feedback_*.md`). Do not cross-pollinate in the other direction.

## Invariants

- Explicit routing only — `crew` prefix required
- Never start implementation without SPEC.md
- Done = acceptance criteria pass, not "looks right"
- Explicit handoffs: every skill step that hands off must name the next step and say "proceed immediately"
- **Before running `tsc` or type-check, check if `node_modules` is a symlink** (`test -L node_modules`). If symlinked, skip — `tsc` follows the symlink and emits `.d.ts` files in the main repo. If `node_modules` is a real directory, type-check is safe.
- **`crew implement` always follows crew-builder's protocol.** Code changes go through crew-builder — via ralph, subagent (Cursor Task tool), or by following crew-builder's inline protocol directly. Never skip the protocol and implement ad-hoc.
