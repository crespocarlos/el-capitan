---
disable-model-invocation: true
name: crew-handoff
description: "Save or resume working state across a context reset or a new session. Triggers: 'crew handoff' (save) and 'crew handoff resume'."
---

**Workflow**: any | **Stage**: session boundary

# Handoff

Preserve the state a fresh session needs, so it continues instead of re-deriving or redoing work.
Code, git, and task files stay authoritative; the handoff only points at them.

## Location

```bash
source ~/.agent/bin/task-env.sh
REPO=$(basename "$(git rev-parse --show-toplevel)")
HANDOFF="${TASK_DIR:-/tmp/crew-handoff-$REPO}/HANDOFF.md"
mkdir -p "$(dirname "$HANDOFF")"
```

Without a task, session start does not announce the handoff; resume needs an explicit `crew handoff
resume`.

## Save (`crew handoff`)

Write `$HANDOFF` (overwrite) from the current session, git state, and task files:

```markdown
# Handoff — <YYYY-MM-DD HH:MM>

## Goal
<one sentence: what this work is for>

## State
- Branch: <branch> @ <short sha>; uncommitted: <files or "none">
- Task: <TASK_DIR or "none">; spec status: <status or "n/a">

## Done
- <completed step with its evidence: command result, file, or commit>

## Next
1. <the very next action, concrete enough to run without re-reading the session>

## Open questions
- <decision the user still owes, with the options>

## Decisions made
- <decision> — <why>

## Pointers
- <path:line or command that a resumed session must read first>
```

Keep it under 60 lines. Record only facts with evidence; leave out narrative. Then output the path
and the `## Next` list.

## Resume (`crew handoff resume`)

Read `$HANDOFF`. If it is missing, say so and stop. Verify the recorded state against git (`git
rev-parse --short HEAD`, `git status --short`) and report any drift before acting. Read every file
under `## Pointers`, restate the goal and next action, and ask the open questions before starting
work that depends on them.
