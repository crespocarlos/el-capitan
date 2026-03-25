# el-capitan

Route `crew <command>` triggers to the right crew member. If the message doesn't start with `crew`, respond normally — no routing.

## Routing table

| Trigger | File to read |
|---|---|
| `crew spec` issue/URL/description | `~/.claude/agents/crew-specwriter.md` |
| `crew implement` | `~/.claude/skills/crew-implement/SKILL.md` |
| `crew diff` | `~/.claude/skills/crew-diff/SKILL.md` |
| `crew commit` | `~/.claude/skills/crew-commit/SKILL.md` |
| `crew open pr` | `~/.claude/skills/crew-open-pr/SKILL.md` |
| `crew review PR` #X or URL | `~/.claude/agents/crew-pr-reviewer.md` |
| `crew address PR` #X or URL | `~/.claude/agents/crew-pr-resolver.md` |
| `crew eval`: suggestion | `~/.claude/skills/crew-eval-pr-comments/SKILL.md` |
| `crew log` | `~/.claude/skills/crew-log/SKILL.md` |
| `crew recall`: question | `~/.claude/skills/crew-recall/SKILL.md` |
| `crew brainstorm` or + topic | `~/.claude/agents/crew-thinker.md` |
| `crew learn` URL/PR/repo/article | `~/.claude/agents/crew-researcher.md` |
| `crew learn` concept/"what if"/ideas | `~/.claude/agents/crew-thinker.md` |
| `crew create issue` description | `~/.claude/skills/crew-create-issue/SKILL.md` |
| `crew cleanup` | `~/.claude/skills/crew-cleanup/SKILL.md` |
| `crew autopilot` | Auto-advance pipeline to next gate (see Pipeline section) |
| `crew status` | Print current pipeline state (see Pipeline section) |

**This table is authoritative.** Read the file, follow its instructions. Do not override with judgment calls.

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

**`crew status`**: prints current pipeline state (task slug, status, next step).

## PROGRESS.md statuses

`DRAFTING` → `APPROVED` → `IMPLEMENTING` → `DIFF_CHECK` → `COMMITTING` → `PR_OPEN` → `DONE`

## Invariants

- Explicit routing only — `crew` prefix required
- Never start implementation without SPEC.md
- Done = acceptance criteria pass, not "looks right"
- Explicit handoffs: every skill step that hands off must name the next step and say "proceed immediately"
- **Before running `tsc` or type-check, check if `node_modules` is a symlink** (`test -L node_modules`). If symlinked, skip — `tsc` follows the symlink and emits `.d.ts` files in the main repo. If `node_modules` is a real directory, type-check is safe.
- **`crew implement` always follows crew-builder's protocol.** Code changes go through crew-builder — via ralph, subagent (Cursor Task tool), or by following crew-builder's inline protocol directly. Never skip the protocol and implement ad-hoc.
