# el-capitan

Route `crew <command>` triggers to the right crew member. If the message doesn't start with `crew`, respond normally — no routing.

## Routing

**Command list is in `crew-router.mdc`** — that file is the single source of truth. Do not duplicate it here.

File path convention:
- Orchestrator agents: `~/.claude/agents/crew-<name>.md` (e.g., `crew-reviewer.md`)
- Persona subagents: `~/.claude/agents/<orchestrator>-<persona>.md` (e.g., `reviewer-adversarial.md`)
- Skills: `~/.claude/skills/<name>/SKILL.md`

All agents and personas are registered at `~/.claude/agents/`. Personas have YAML frontmatter: `name`, `description`, `model`, `tools`, `maxTurns`.

## How to invoke agents (CRITICAL)

**Orchestrator agents** (crew-reviewer, crew-specwriter, crew-pr-resolver) run **inline in the main session** — read their protocol from `~/.claude/agents/crew-<name>.md` and execute it directly. Do NOT dispatch them via Agent tool. Claude Code does not support nested Agent tool calls (subagents cannot spawn subagents), so orchestrators must run in the main session to be able to dispatch persona subagents.

**Persona subagents** (reviewer-adversarial, specwriter-scope, specwriter-adversarial, etc.) are dispatched BY the orchestrator via the Agent tool from the main session — each gets its own context window.

Dispatch fallback priority (when Agent tool is unavailable):
1. **`claude -p` file-based dispatch** — parallel CLI processes
2. **Inline sequential** — degraded; ordering bias; only when no other option

`crew autopilot` and `crew status` are handled inline — see Pipeline section below.

**This routing is authoritative.** Read the file, follow its instructions. Do not override with judgment calls.

**Task state**: resolve via `~/.agent/bin/resolve-task-dir.py`. Scans `~/.agent/tasks/*/.task-id`, matches `repo_remote_url` + `branch`.

## Pipeline

```
spec → [Gate 1: approve spec] → implement → review → commit → [Gate 2: approve message] → open PR → done
```

**`crew autopilot`**: chains from current state to next gate. Not a mode toggle — means "advance from here." If a step fails, pauses and surfaces the error. No auto-retry.

**`crew status`**: prints current pipeline state derived from git/gh state. See crew-orchestrator.mdc for the full logic.

**`crew health`**: runs five health checks inline (symlinks, hooks, jq, gh auth, active SPEC.md). Auto-runs when `crew status` finds no active task.

**`crew abandon`**: gracefully abandons the current task — stashes changes, writes SESSION.md stub, appends ABANDONED to PROGRESS.md.

`crew start build` → crew-specwriter. `crew start review-cycle <PR#>` → crew-pr-resolver. (Alias layer — no new state.)

## PROGRESS.md

Append-only. Format: `[YYYY-MM-DD HH:MM] TRANSITION: X → Y`. `crew status` reads git/gh, not this file.

## Memory

Two systems, keep them partitioned. Journal (`~/.agent/journal/`) — long-term, updated manually via `crew log`. Auto-memory (`~/.claude/projects/*/memory/`) — session-scoped, auto-saved. `crew log` is the only bridge — do not cross-pollinate.

## Invariants

- Explicit routing only — `crew` prefix required
- Never start implementation without SPEC.md
- Done = acceptance criteria pass, not "looks right"
- Explicit handoffs: every skill step that hands off must name the next step and say "proceed immediately"
- **Before running `tsc` or type-check, check if `node_modules` is a symlink** (`test -L node_modules`). If symlinked, skip — `tsc` follows the symlink and emits `.d.ts` files in the main repo. If `node_modules` is a real directory, type-check is safe.
- **`crew implement` always follows crew-builder's protocol.** Code changes go through crew-builder — via ralph, subagent (Cursor Task tool), or by following crew-builder's inline protocol directly. Never skip the protocol and implement ad-hoc.
