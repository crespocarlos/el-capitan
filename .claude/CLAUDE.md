# Personal preferences

**Role:** Principal Software Engineer at Elastic (Kibana). TypeScript / React / Node. Testing: Jest, React Testing Library, Playwright. Working heavily with LLMs, prompt engineering, eval frameworks, and agentic workflows.

## Engineering philosophy

- **Build first, refine later** — shortest path to something that works. Prototype before designing, fail fast.
- **Simplicity over scope creep** — the best code is the code you don't write. Resist abstractions until the third use case earns them.
- **Performance is UX** — latency and bundle size are user experience. Prefer patterns that scale over reactive band-aids.
- **Small PRs ship faster** — reviewable, revertable, mergeable. Big PRs rot.
- **No magic globals** — explicit dependencies, explicit config. Nothing hidden in module state.

## How I expect agents to work

- **Analyze before writing** — find existing libs, utilities, and patterns before adding anything. Don't introduce a new convention when one already exists.
- **No code without tests** — every change includes tests. Jest for unit/integration, React Testing Library for components, Playwright for E2E.
- **Verify changes** — run it, check the output, read the result. Don't assume it worked.
- **Push back early** — if something is ambiguous, wrong, or non-trivial, say so before acting. Don't silently assume; propose a plan first.
- **Be direct** — say what you did, what worked, what failed. 1–3 sentences. No preamble, no padding, no jargon. If it's broken, say it's broken; if you don't know, say so — don't make things up.
- **Consistency** — if you touch one file in a set, check the rest follow the same conventions.
- **Encapsulate at the right layer** — error handling, validation, and cleanup belong in the component that owns the concern, not spread across consumers.

## TypeScript hard rules

- No `any`. No `unknown` unless it's a true boundary with immediate narrowing.
- Explicit types on function signatures — don't rely on inference for public APIs.
- No long functions — extract named helpers beyond ~150 lines.
- Check if functionality already exists before writing new code.
- No functions with 4+ positional parameters, prefer objects.

## LLM / eval / agentic work

- **Prompts are code** — version them, test them, treat regressions seriously.
- **Evals over vibes** — don't claim a prompt change is better without a measurement. Define the metric first.
- **Scope agentic steps tightly** — each agent step should have a single clear output. Avoid steps that both decide and act.
- **Fail loudly in agents** — silent failures in agentic pipelines are worse than crashes. Surface errors explicitly.

---

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

Two systems, keep them partitioned. Journal (`~/.agent/journal/`) — long-term, updated manually via `crew log`. Auto-memory (`~/.claude/projects/*/memory/`) — session-scoped, auto-saved. `crew log` is the only bridge — do not cross-pollinate.

## Invariants

- Explicit routing only — `crew` prefix required
- Never start implementation without SPEC.md
- Done = acceptance criteria pass, not "looks right"
- Explicit handoffs: every skill step that hands off must name the next step and say "proceed immediately"
- **Before running `tsc` or type-check, check if `node_modules` is a symlink** (`test -L node_modules`). If symlinked, skip — `tsc` follows the symlink and emits `.d.ts` files in the main repo. If `node_modules` is a real directory, type-check is safe.
- **`crew implement` always follows crew-builder's protocol.** Code changes go through crew-builder — via ralph, subagent (Cursor Task tool), or by following crew-builder's inline protocol directly. Never skip the protocol and implement ad-hoc.
