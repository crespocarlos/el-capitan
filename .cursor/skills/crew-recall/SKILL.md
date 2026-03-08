---
name: crew-recall
description: "Search journal entries by meaning or metadata. Trigger: 'crew recall: <question>'."
---

# Journal Recall

## When Invoked

### Step 1 — Classify the query

Determine what the user wants:

- **Overview** ("what do you know?", "what's stored?", "journal status") → run `journal-search summary`
- **Repo patterns** ("what do you know about kibana?") → run `journal-search auto-recall <repo>`
- **Specific question** ("how do retries work?", "what did I learn about worktrees?") → run `journal-search query "<text>"`
- **Filtered search** (by type, tag, date) → fall back to ripgrep

Auto-detect repo scope if inside a repo:

```bash
REPO=$(basename $(git rev-parse --show-toplevel) 2>/dev/null || echo "")
```

### Step 2 — Run the search

**Overview:**
```bash
journal-search summary
```

**Repo patterns:**
```bash
journal-search auto-recall "$REPO" --top 5
```

**Semantic search (preferred for questions):**
```bash
journal-search query "<search text>" --top 5
```

**Structured search (fallback for metadata filters):**
```bash
rg "<pattern>" ~/.agent/journal/ --context 10
```

Metadata filters via ripgrep:
- Type: `rg "^\*\*Type:\*\* pattern" ~/.agent/journal/`
- Tag: `rg "#agent-memory" ~/.agent/journal/`
- Repo: `rg "^\*\*Repo:\*\* kibana" ~/.agent/journal/`
- Date: search only files named `YYYY-MM.md` where `YYYY-MM >= DATE`

### Step 3 — Present results

- **Summary queries**: show the overview as-is, highlight interesting stats.
- **Specific queries**: for each match, show date, summary, and the most relevant field (Key idea, Rule, What I learned, Decisions made).
- **Questions** ("how does X work?"): synthesize an answer from matching entries, don't just list them.

If many results (>5), group by type and summarize themes. If nothing matches, say so and suggest broadening.

## Rules

- Always use `journal-search` commands — don't read journal files sequentially
- Read `~/.agent/PROFILE.md` for context on what the user cares about
- Present results concisely; the user wants answers, not raw entries
- When inside a repo, bias toward that repo's entries unless the query is clearly cross-repo
