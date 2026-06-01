---
name: crew-recall
description: "Search journal entries by meaning or metadata. Trigger: 'crew recall: <question>'."
---

# Journal Recall

Detect current repo:

```bash
REPO=$(basename $(git rev-parse --show-toplevel) 2>/dev/null || echo "")
```

## Commands

**Overview** ("what do you know?", "journal status"):
```bash
~/.agent/bin/journal-search.py summary
```

**Repo patterns** ("what do you know about kibana?"):
```bash
~/.agent/bin/journal-search.py auto-recall "$REPO" --top 5
```

**Specific question** ("how do retries work?", "what did I learn about worktrees?"):
```bash
~/.agent/bin/journal-search.py query "<search text>" --top 5
```

**Repo-scoped** (boost + filter to a specific repo):
```bash
~/.agent/bin/journal-search.py query "<search text>" --repo el-capitan --top 5
```

**Metadata filter fallback** (by tag, repo, date):
```bash
rg "#agent-memory" ~/.agent/journal/
rg "^\*\*Repo:\*\* kibana" ~/.agent/journal/
```

## Rules

- Always use `journal-search.py` — don't read journal files sequentially
- When inside a repo, bias toward that repo's entries unless the query is clearly cross-repo
- For questions ("how does X work?"): synthesize an answer from matches, don't just list entries
- If results seem empty or stale, run `journal-search index` to rebuild the `journal_v2` collection
