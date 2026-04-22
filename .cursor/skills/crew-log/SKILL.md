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

If `TASK_DIR` is empty, no active task — skip pipeline artifact harvesting.

Read `$TASK_DIR/SESSION.md` if it exists — auto-captured context from pipeline skills.

Read `~/.agent/PROFILE.md` for user context.

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

1. If the entry has a `### Promoted` section, append each bullet to `~/.agent/PROFILE.md` under a `## Promoted facts` heading (create the heading if absent). No confirmation needed — the user wrote them explicitly. These are the hot-tier facts that stay in-context permanently.

2. If artifacts contain patterns worth promoting (repeated workarounds, discovered constraints, rules that should survive) that weren't already in `### Promoted`, suggest them:

   > "These look worth adding to `### Promoted`: [list]"
   > Only add if user confirms.

3. Clear `$TASK_DIR/SESSION.md` (the buffer has been flushed to the journal).

4. Offer the creative handoff:
   > "Want crew-thinker to connect this session to past patterns and generate ideas?"

## Rules

- Populate bullets from REPORT.md, SESSION.md, and git log — do not ask for what can be inferred
- Tag entities inline in bullets: `[file:]`, `[repo:]`, `[tool:]`, `[concept:]`, `[url:]`
- `### Promoted` bullets are written to PROFILE.md immediately — no confirmation needed
- Triggerable any time: after implementation, after PR review, after learning, or end of day
- Never modify existing journal entries — only append

## Auto-clarity override

Drop to plain language before:

- Presenting the final journal entry draft — show it in full before writing; journal entries are append-only and there is no delete command

This skill is otherwise low-risk (append-only, local files). No other override conditions apply.
