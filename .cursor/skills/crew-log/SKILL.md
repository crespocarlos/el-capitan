---
name: crew-log
description: "Log an agentic engineering session to the journal. Trigger: 'crew log'."
---

# Journal Entry

## When Invoked

### Step 1: Gather context

```bash
REPO=$(basename $(git rev-parse --show-toplevel) 2>/dev/null || echo "unknown")
BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
BRANCH_DIR=~/.agent/tasks/$REPO/$BRANCH
MONTH=$(date +%Y-%m)
JOURNAL_FILE=~/.agent/journal/$MONTH.md
```

Resolve `TASK_DIR` by finding the active task under `$BRANCH_DIR`:
1. Scan `$BRANCH_DIR/*/SPEC.md` — filter to non-DONE specs
2. If exactly one → use its parent as `TASK_DIR`
3. If multiple → use the most recently modified
4. Backward compat: if `$BRANCH_DIR/SPEC.md` exists (old flat layout) → use `BRANCH_DIR` as `TASK_DIR`
5. If none found → `TASK_DIR` is unset (no active task, skip pipeline artifact harvesting)

Read `$TASK_DIR/SESSION.md` if it exists — auto-captured context from pipeline skills.

Read `~/.agent/PROFILE.md` for user context.

### Step 2: Pre-populate from pipeline artifacts

Before asking anything, harvest technical facts:

```bash
# Implementation report (tasks, files changed, errors)
cat "$TASK_DIR/REPORT.md" 2>/dev/null

# Last commit message (intent and scope)
git log -1 --format="%B" 2>/dev/null

# Files touched (fallback if REPORT.md unavailable)
git diff --name-only HEAD~1 2>/dev/null
```

Use these to pre-fill:
- **What I did** — from REPORT.md summary or commit message
- **Files touched** — from REPORT.md "Files Changed" or `git diff --name-only`
- **What broke / surprised me** — from REPORT.md "Errors" section if present

Show the pre-filled draft and say: "Here's what I captured automatically. What should I add?"

### Step 3: Fill in the gaps

Ask only for the human layer — 4 targeted questions:

1. **What did you learn?** — the one transferable insight from this session
2. **Decisions made?** — key choices and why (not what, why)
3. **What broke or surprised you?** — if not already captured from REPORT.md
4. **Anything to promote to rules?** — conventions worth adding to CLAUDE.md or AGENTS.md

Auto-fill from git state what isn't already known:
- **Repo** and **Branch**: from git
- **Tags**: suggest based on repo, file paths, and session content

### Step 4: Write the entry

Append to `$JOURNAL_FILE` (create if it doesn't exist):

```markdown
---
## DATE — SUMMARY

**Type:** engineering
**Tags:** #tag1 #tag2
**Repo:** repo-name
**Branch:** branch-name
**Files touched:** path/to/file.ts, path/to/other.ts
**What I did:** 1-2 sentences
**Hypothesis:** (optional) — what you expected before starting
**Decisions made:** key choices and why
**What broke / surprised me:** errors, wrong assumptions, corrections
**What I learned:** transferable insight
**Outcome:** (optional) — fill after PR merges: did it work? any friction in review?
**Connections:** links to previous entries or patterns, or "none"
**Promote to rules:** conventions worth remembering, or "none"
**Open questions:** unresolved questions, or "none"
```

Use `$(date +%Y-%m-%d)` for the date. Derive the one-line summary from what the user did.

### Step 5: Index the entry

If `~/.agent/tools/journal-search.py` is available, index the new entry:

```bash
~/.agent/tools/journal-search.py add "$JOURNAL_FILE" --entry "$(date +%Y-%m-%d)"
```

The tool verifies the entry was stored and prints what it indexed. If it fails, surface the error to the user.

### Step 6: After writing

1. If the user provided "Promote to rules" candidates, offer:
   > "These look worth persisting: [list]. Want me to add them to CLAUDE.md or AGENTS.md?"
   If yes, add the rules to the appropriate file (CLAUDE.md for global, AGENTS.md for repo-specific).

2. Clear `$TASK_DIR/SESSION.md` (the buffer has been flushed to the journal).

3. Offer the creative handoff:
   > "Want crew-thinker to connect this session to past patterns and generate ideas?"

## Rules

- Keep entries concise — 2-3 sentences per field max
- Pre-populate from REPORT.md and git log before asking; don't ask what you can infer
- Triggerable any time: after implementation, after PR review, after learning, after support investigation, or just at end of day
- Never modify existing journal entries — only append
- Engineering entries use `**Type:** engineering`
- Hypothesis and Outcome fields are optional — never block on them if the user skips
