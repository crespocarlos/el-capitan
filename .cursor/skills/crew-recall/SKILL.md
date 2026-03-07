---
name: crew-recall
description: "Search journal entries by meaning or metadata. Trigger: 'crew recall: <question>'."
---

# Journal Recall

## When Invoked

### Step 1 — Parse the query

Determine what the user is looking for. Extract:
- **Search text**: the topic, concept, or question
- **Filters** (optional): type (`engineering`, `learning`, `pattern`), tags, repo, date range

Auto-detect repo scope: if working inside a repo, default to that repo unless the user asks for something broader.

```bash
REPO=$(basename $(git rev-parse --show-toplevel) 2>/dev/null || echo "")
```

### Step 2 — Semantic search (preferred)

If `journal-search` is available, use it first:

```bash
journal-search query "<search text>" --top 5
```

This finds entries by meaning, not just keywords. It works across all monthly journal files and all entry types (engineering, learning, pattern).

### Step 3 — Structured search (supplement or fallback)

Search across all monthly journal files using ripgrep:

```bash
rg "<pattern>" ~/.agent/journal/ --context 10
```

Support these filters by grepping metadata fields:

- `--type`: `rg "^\*\*Type:\*\* pattern" ~/.agent/journal/`
- `--tag`: `rg "#agent-memory" ~/.agent/journal/`
- `--repo`: `rg "^\*\*Repo:\*\* kibana" ~/.agent/journal/` or `rg "^\*\*Scope:\*\* kibana" ~/.agent/journal/`
- `--after DATE`: search only files named `YYYY-MM.md` where `YYYY-MM >= DATE`

For pattern-specific queries (e.g., "what are the rules for kibana?"), combine type + scope:

```bash
rg "^\*\*Scope:\*\* $REPO" ~/.agent/journal/ -l 2>/dev/null | xargs rg "^\*\*Rule:\*\*" 2>/dev/null
```

Combine filters: grep for the metadata field, then intersect with the search text.

### Step 4 — Present results

For each matching entry, show:
- **Date and summary** (the `## DATE — SUMMARY` line)
- **Type and tags**
- **The most relevant field** depending on type:
  - Pattern entries: show the **Rule** and **Context**
  - Engineering entries: show **What I learned** or **Decisions made**
  - Learning entries: show **Key idea** or **What I learned**

If there are many results (>5), group by type and summarize themes rather than listing all entries.

If the user asks a question (e.g., "how does X work?"), synthesize an answer from the matching entries rather than just listing them.

If nothing matches, say so and suggest broadening the search.

## Rules

- Always try semantic search first if `journal-search` is available
- Fall back to grep for metadata-specific filters (type, tag, repo, date)
- Read `~/.agent/PROFILE.md` for context on what the user cares about
- Don't read every journal file sequentially — use targeted search
- Present results concisely; the user wants answers, not raw entries
- When inside a repo, bias results toward that repo's entries unless the query is clearly cross-repo
