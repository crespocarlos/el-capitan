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

**Orchestrator agents** (crew-reviewer, crew-specwriter, crew-thinker, crew-researcher, crew-pr-resolver) are dispatched via the Agent tool — never read inline. Pass the user's raw request as the prompt. Each orchestrator runs in its own context window, keeping the main session lean.

**Persona subagents** (reviewer-adversarial, specwriter-scope, thinker-builder, etc.) are dispatched BY the orchestrator via the Agent tool — each gets its own context window.

Dispatch fallback priority (when Agent tool is unavailable):
1. **`claude -p` file-based dispatch** — parallel CLI processes
2. **Inline sequential** — degraded; ordering bias; only when no other option

`crew autopilot` and `crew status` are handled inline — see Pipeline section below.

**This routing is authoritative.** Read the file, follow its instructions. Do not override with judgment calls.

## Task state

```bash
# Resolve TASK_DIR via .task-id reverse lookup.
# Hard (exits 1 if no git remote or not on a branch — for pipeline commands):
TASK_DIR=$(~/.agent/tools/resolve-task-dir.sh) || exit 1

# Soft (returns empty string — for session capture / optional logging):
TASK_DIR=$(~/.agent/tools/resolve-task-dir.sh 2>/dev/null || echo "")
```

Find active task: scan `~/.agent/tasks/*/.task-id`, match on `repo_remote_url` + `branch` to find the UUID task directory. `TASK_DIR` is set to the UUID directory (`~/.agent/tasks/<uuid>/`) containing `SPEC.md`, `PROGRESS.md`, etc. If multiple match, prefer non-DONE; if all DONE, pick most recent `created_at`.

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
