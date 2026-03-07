---
name: crew-remember
description: "Persist a pattern, convention, or rule to the journal (embedded + searchable). Trigger: 'crew remember: <pattern>'."
---

# Remember

Write a pattern to the journal with embeddings so it's discoverable via `crew recall`. Optionally escalate critical rules to static config files.

## When Invoked

### Step 1 — Identify the pattern

Extract the pattern, convention, or rule. Sources:

- User says it directly: "remember that we always use Emotion for styles"
- crew-log flagged it in `**Promote to rules:**`
- crew-thinker flagged it in `**Patterns emerging:**` (3+ occurrences)

Formulate it as a clear, actionable statement. One sentence preferred. Example:
> "Always use Emotion for component styles; never use inline `style=` attributes."

### Step 2 — Check for duplicates

If `journal-search` is available, search for similar patterns:

```bash
journal-search query "<pattern summary>" --top 3 2>/dev/null || true
```

Also search with ripgrep for exact matches:

```bash
rg -l "<key phrase>" ~/.agent/journal/ 2>/dev/null
```

If a similar pattern already exists, show it and ask:
> "Found a related entry from [date]: [summary]. Want to update it, or is this distinct enough to add as a new one?"

### Step 3 — Determine scope

Detect from context, or ask:

- **Repo:** `$(basename $(git rev-parse --show-toplevel) 2>/dev/null || echo "general")`
- If the pattern references a specific repo (naming conventions, test structure, dependency choices), tag it with that repo.
- If it's about how the user works in general (agent preferences, workflow, review approach), tag it as `#global`.

### Step 4 — Write to journal

```bash
JOURNAL_FILE=~/.agent/journal/$(date +%Y-%m).md
mkdir -p ~/.agent/journal
```

Present the entry and ask: "Look good?"

Only write after the user approves.

```markdown
---
## DATE — Pattern: SUMMARY

**Type:** pattern
**Tags:** #pattern #repo-name (or #global) #domain-tags
**Scope:** repo-name | global
**Rule:** the actionable one-liner
**Context:** why this matters — what went wrong without it, or what goes right with it
**Connections:** links to past entries where this pattern appeared, or "none"
**Open questions:** edge cases or situations where this might not apply, or "none"
```

### Step 5 — Embed

Index the entry if `journal-search` is available:

```bash
journal-search add "$JOURNAL_FILE" --entry "$(date +%Y-%m-%d)" 2>/dev/null || true
```

### Step 6 — Escalation (optional)

Only offer if the pattern is a **hard rule that must be active in every session** — something where missing it causes real damage (data loss, broken builds, security).

> "This is now searchable via `crew recall`. Should I also pin it as a hard rule in [CLAUDE.md / AGENTS.md]? Only needed if agents must follow this even when they don't search."

If yes:
- **Repo-specific** → the repo's `AGENTS.md`
- **Global** → `~/.claude/CLAUDE.md`

Append the rule. If the file doesn't exist, create it with a minimal header.

### Step 7 — Confirm

Show what was done:
> "Remembered: [rule summary]. Stored in journal ([month file]) and indexed for search."
> (If escalated: "Also pinned in [target file].")

## Rules

- Always ask before writing — same pattern as crew-commit
- One pattern at a time; if the user has multiple, process them sequentially
- Patterns should be specific and actionable, not vague guidance
- Never modify existing journal entries — only append new ones
- The journal entry is the primary store; static files are an optional escalation
- Use `**Type:** pattern` (not `engineering` or `learning`) to distinguish from other entries
