---
name: crew-recall
description: "Search journal entries by meaning or metadata. Use when the user says 'recall X', 'search journal for X', 'what did we learn about X', or 'find past work on X'."
---

# Journal Recall

## When Invoked

### Step 1 — Parse the query

Determine what the user is looking for. Extract:
- **Search text**: the topic, concept, or question
- **Filters** (optional): type, tags, repo, date range

### Step 2 — Semantic search (preferred)

If `journal-search` is available, use it first:

```bash
journal-search query "<search text>" --top 5
```

This finds entries by meaning, not just keywords. It works across all monthly journal files.

### Step 3 — Structured search (fallback or supplement)

Search across all monthly journal files using ripgrep:

```bash
rg "<pattern>" ~/.agent/journal/ --context 10
```

Support these filters by grepping metadata fields:

- `--type`: `rg "^\*\*Type:\*\* engineering" ~/.agent/journal/`
- `--tag`: `rg "#agent-memory" ~/.agent/journal/`
- `--repo`: `rg "^\*\*Repo:\*\* kibana" ~/.agent/journal/`
- `--after DATE`: search only files named `YYYY-MM.md` where `YYYY-MM >= DATE`

Combine filters: grep for the metadata field, then intersect with the search text.

### Step 4 — Present results

For each matching entry, show:
- **Date and summary** (the `## DATE — SUMMARY` line)
- **Type and tags**
- **The most relevant field** (What I learned, Key idea, or the matching context)

If there are many results (>5), summarize themes across them rather than listing all entries.

If nothing matches, say so and suggest broadening the search.

## Rules

- Always try semantic search first if `journal-search` is available
- Fall back to grep for metadata-specific filters (type, tag, repo, date)
- Read `~/.agent/PROFILE.md` for context on what the user cares about
- Don't read every journal file sequentially — use targeted search
- Present results concisely; the user wants answers, not raw entries
