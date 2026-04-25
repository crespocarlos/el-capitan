---
name: crew-log
description: "Log an agentic engineering session to the journal. Trigger: 'crew log'."
---

# Journal Entry

## When Invoked

### Step 1: Gather context

```bash
MONTH=$(date +%Y-%m)
JOURNAL_FILE=~/.agent/journal/$MONTH.md
```

Resolve `TASK_DIR` via `.task-id` reverse lookup:

```bash
TASK_DIR=$(~/.agent/bin/resolve-task-dir.py 2>/dev/null || echo "")
```

If `TASK_DIR` is empty, no active task — skip pipeline artifact harvesting. In this case, the session conversation is the primary source (see Step 2).

Read `$TASK_DIR/SESSION.md` if it exists — auto-captured context from pipeline skills.

### Step 2: Harvest artifacts

Ingest everything available — read and include the full content, not just metadata:

```bash
# Full implementation report — read as-is
cat "$TASK_DIR/REPORT.md" 2>/dev/null

# SESSION.md — verbatim notes captured during the pipeline
cat "$TASK_DIR/SESSION.md" 2>/dev/null

# Commit log — last 5 commits on current branch
git log -5 --format="%h %s" 2>/dev/null

# Files touched (fallback if REPORT.md unavailable)
git diff --name-only HEAD~1 2>/dev/null
```

**Session conversation fallback** — if no active task (`TASK_DIR` is empty) or REPORT.md/SESSION.md are absent, synthesize from the current session conversation instead. This covers `crew review`, `crew review idea`, brainstorm sessions, and any conversation that doesn't go through the build pipeline. Extract: what was discussed, decisions made, things learned, any proposals or plans developed, and notable insights worth preserving across sessions.

Derive all structured fields from these sources. Do not ask for anything that can be inferred. If SESSION.md is substantial (>200 lines), include it verbatim under a `## Session notes` block rather than summarizing — indexing raw content is cheap and lossless.

After composing the draft, show it and ask a single open question:

> "Anything to add before I write this?"

If the user says nothing or "no", write immediately. Do not prompt for specific fields.

### Step 3: Write the entry

Append to `$JOURNAL_FILE` (create if it doesn't exist):

Tag entities inline in every bullet using `[type:value]` syntax — `[file:]`, `[repo:]`, `[tool:]`, `[concept:]`, `[url:]`. These are indexed as metadata for entity-filtered recall.

```markdown
---

## DATE — SUMMARY

**Tags:** #tag1 #tag2
**Repo:** repo-name

### Done

- [tool:x] or [file:x] entity-tagged bullets derived from git log, commit messages, REPORT.md

### Absorbed

- (omit section if nothing was read or learned)

### Implemented

- (omit section if nothing new was created)

### Promoted

- durable rules/constraints to carry forward permanently (omit section if none)

### Open

- (omit section if no unresolved items)

### Raw session

<verbatim SESSION.md content if present and substantial>
```

Use `$(date +%Y-%m-%d)` for the date. Derive the one-line summary from what happened.

### Step 4: Index the entry

If `~/.agent/bin/journal-search.py` is available, index the new entry:

```bash
~/.agent/bin/journal-search.py add "$JOURNAL_FILE" --entry "$(date +%Y-%m-%d)"
```

The tool verifies the entry was stored and prints what it indexed. If it fails, surface the error to the user.

### Step 5: After writing

1. If the entry has a `### Promoted` section, note those facts to the user — they may want to add them to `~/.claude/CLAUDE.md` or `~/.cursor/rules/personal.mdc` for permanent context.

2. If artifacts contain patterns worth promoting (repeated workarounds, discovered constraints, rules that should survive) that weren't already in `### Promoted`, suggest them:

   > "These look worth adding to `### Promoted`: [list]"
   > Only add if user confirms.

3. Scan the session for preference violations — moments where an agent ignored or contradicted the rules in `~/.claude/CLAUDE.md` or `~/.cursor/rules/personal.mdc`. If any found, surface them:

   > "Preference violations this session: [list]. Worth updating `personal.mdc` to be more explicit?"

4. **Drift check** — read the first `## How I expect agents to work` block in both `~/.claude/CLAUDE.md` and `~/.cursor/rules/personal.mdc`. If they differ in substance (not just whitespace/formatting), surface:

   > "`CLAUDE.md` and `personal.mdc` preferences have drifted — consider syncing them. Key differences: [list]"

5. Clear `$TASK_DIR/SESSION.md` (the buffer has been flushed to the journal).

## Rules

- Populate bullets from REPORT.md, SESSION.md, and git log — do not ask for what can be inferred
- Tag entities inline in bullets: `[file:]`, `[repo:]`, `[tool:]`, `[concept:]`, `[url:]`
- `### Promoted` bullets are surfaced to the user for manual addition to `~/.claude/CLAUDE.md` or `~/.cursor/rules/personal.mdc`
- Triggerable any time: after implementation, after PR review, after learning, or end of day
- Never modify existing journal entries — only append

## Auto-clarity override

Drop to plain language before:

- Presenting the final journal entry draft — show it in full before writing; journal entries are append-only and there is no delete command

This skill is otherwise low-risk (append-only, local files). No other override conditions apply.
