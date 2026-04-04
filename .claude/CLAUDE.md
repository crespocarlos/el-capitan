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
# Resolve TASK_DIR for the current repo+branch via .task-id reverse lookup.
# Assumption: remote URL is stable after spec creation (SSH vs HTTPS not normalized).
# If no remote or no branch, skip resolution and print an error.
CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")

if [ -z "$CURRENT_REMOTE" ]; then
  echo "No git remote configured; cannot resolve task state." >&2; exit 1
fi
if [ -z "$CURRENT_BRANCH" ]; then
  echo "Not on a branch; crew commands require an active branch." >&2; exit 1
fi

# Collect all matching task dirs with their created_at and SPEC.md status
MATCHES=()
for task_id_file in ~/.agent/tasks/*/.task-id; do
  [ -f "$task_id_file" ] || continue
  file_remote=$(python3 -c "import json; d=json.load(open('$task_id_file')); print(d.get('repo_remote_url',''))" 2>/dev/null || echo "PARSE_ERROR")
  file_branch=$(python3 -c "import json; d=json.load(open('$task_id_file')); print(d.get('branch',''))" 2>/dev/null || echo "PARSE_ERROR")
  if [ "$file_remote" = "PARSE_ERROR" ] || [ "$file_branch" = "PARSE_ERROR" ]; then
    echo "Warning: malformed .task-id at $task_id_file — skipping." >&2
    continue
  fi
  if [ "$file_remote" = "$CURRENT_REMOTE" ] && [ "$file_branch" = "$CURRENT_BRANCH" ]; then
    created_at=$(python3 -c "import json; d=json.load(open('$task_id_file')); print(d.get('created_at',''))" 2>/dev/null || echo "")
    MATCHES+=("$created_at $(dirname "$task_id_file")")
  fi
done

TASK_DIR=""
if [ "${#MATCHES[@]}" -eq 0 ]; then
  TASK_DIR=""  # No active task
elif [ "${#MATCHES[@]}" -eq 1 ]; then
  TASK_DIR="${MATCHES[0]#* }"  # Strip the created_at prefix
else
  # Multiple matches: prefer non-DONE, then most recent created_at
  BEST=""
  BEST_DATE=""
  for entry in "${MATCHES[@]}"; do
    dir="${entry#* }"
    date="${entry%% *}"
    spec_status=$(grep -A1 "^## Status" "$dir/SPEC.md" 2>/dev/null | tail -1 | tr -d ' ' || echo "")
    if [ "$spec_status" != "done" ]; then
      if [ -z "$BEST" ] || [[ "$date" > "$BEST_DATE" ]]; then
        BEST="$dir"; BEST_DATE="$date"
      fi
    fi
  done
  # If all are DONE, pick most recent
  if [ -z "$BEST" ]; then
    BEST=$(printf '%s\n' "${MATCHES[@]}" | sort -r | head -1)
    BEST="${BEST#* }"
  fi
  TASK_DIR="$BEST"
  echo "Multiple tasks found for this repo+branch. Using: $TASK_DIR (most recent non-DONE)." >&2
fi
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
