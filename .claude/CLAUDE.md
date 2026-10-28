# Shared rules

Canonical rule files, shared with Cursor:

@~/.cursor/rules/personal.mdc
@~/.cursor/rules/prompt-engineering.mdc
@~/.cursor/rules/typescript.mdc

---

# el-capitan

Route `crew <command>` triggers to the right crew member. If the message doesn't start with `crew`, respond normally — no routing.

## Routing

See `rules/crew-router.mdc`.

**Mapped workflows:** for an explicit `crew <command>`, do **not** call Claude's
`Skill` tool. Read the routed `~/.claude/skills/<mapped-skill>/SKILL.md` file
and execute its workflow inline. Skills without `disable-model-invocation: true`
may also activate for a matching non-`crew` request.

## How to invoke agents (CRITICAL)

**Orchestrator agents** (crew-reviewer, crew-specwriter, crew-pr-resolver) run **inline in the main session** — read their protocol from `~/.claude/agents/crew-<name>.md` and execute it directly. Do NOT dispatch them via Agent tool. Claude Code does not support nested Agent tool calls (subagents cannot spawn subagents), so orchestrators must run in the main session to be able to dispatch persona subagents.

**Persona subagents** (reviewer-adversarial, specwriter-scope, specwriter-adversarial, etc.) are dispatched BY the orchestrator via the Agent tool from the main session — each gets its own context window.

Dispatch fallback priority (when Agent tool is unavailable):
1. **`claude -p` file-based dispatch** — parallel CLI processes
2. **Inline sequential** — degraded; ordering bias; only when no other option

**This routing is authoritative.** Read the file, follow its instructions. Do not override with judgment calls.

**Task state**: resolve via `~/.agent/bin/resolve-task-dir.py`. Scans `~/.agent/tasks/*/.task-id`, matches `repo_remote_url` + `branch`.

## Pipeline

```
spec → [Gate 1: approve spec] → implement → review → commit → [Gate 2: approve message] → open PR → done
```

Drive each step manually: `crew spec` → `crew implement` → `crew review` → `crew commit` → `crew open pr`.

## PROGRESS.md

Append-only. Format: `[YYYY-MM-DD HH:MM] TRANSITION: X → Y`. Pipeline state is derived from git/gh — not this file.

## Memory

The shared store at `~/.agent/memory` is the durable, harness-neutral source
of truth. It contains typed, repo-scoped Markdown units; SQLite FTS5 is only a
rebuildable retrieval index. At task start, read session context through
`mem.py`; code, documentation, and user instructions always override memory.

Do not write memories automatically. Use `crew remember:` only for durable
information not available from code, git, or rules. `crew memory seed` drafts
journal candidates for explicit user approval. Existing Claude Code or Codex
memory may be imported as a read-only source with `mem.py ingest`; never
reconfigure or modify its source repository.

## Invariants

- Explicit routing only — `crew` prefix required
- Never start implementation without SPEC.md
- Done = acceptance criteria pass, not "looks right"
- Explicit handoffs: every skill step that hands off must name the next step and say "proceed immediately"
- **Before running `tsc` or type-check, check if `node_modules` is a symlink** (`test -L node_modules`). If symlinked, skip — `tsc` follows the symlink and emits `.d.ts` files in the main repo. If `node_modules` is a real directory, type-check is safe.
- **`crew implement` always follows crew-builder's protocol.** Code changes go through crew-builder — via subagent (Cursor Task tool) or by following crew-builder's protocol directly. Never skip the protocol and implement ad-hoc.

<!-- el-capitan:memory -->
Run `~/.agent/bin/mem.py context --mode session` at task start and follow `~/.cursor/skills/crew-memory/references/contract.md`.
<!-- /el-capitan:memory -->
