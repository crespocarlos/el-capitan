# Journal Entry Schema

Reference for crew-log, crew-researcher, and crew-thinker. Entries are written to monthly files in `~/.agent/journal/YYYY-MM.md`.

The journal is a memory system. Each entry is indexed at two levels: the full entry (for context queries) and each individual bullet (for entity-filtered retrieval). This means the indexable unit is the bullet, not the entry — write bullets that are self-contained facts.

Three retrieval axes:

- **Done** — actions taken, changes made, commits shipped
- **Absorbed** — things read, learned, or understood
- **Implemented** — concrete artifacts built: features, fixes, scripts, configs

Sections with no content are omitted.

## Entity tags

Tag the entities each bullet mentions using `[type:value]` inline syntax. These are extracted as metadata and enable entity-filtered search alongside semantic search.

| Tag | Example |
|-----|---------|
| `repo:` | `[repo:el-capitan]` |
| `file:` | `[file:.agent/bin/get-diff.sh]` |
| `dir:` | `[dir:.agent/bin/]` |
| `tool:` | `[tool:dispatch_subagents.py]` |
| `concept:` | `[concept:Mem0 memory extraction]` |
| `branch:` | `[branch:feat/memory-redesign]` |
| `pr:` | `[pr:42]` |

For source URLs, cite inline in the bullet text: `(https://docs.letta.com/letta-code/memory)`. No fetch is triggered — these are plain strings.

Query with entity filter: `journal-search.py query "..." --entity repo:el-capitan`

## Schema

```markdown
---
## DATE — SUMMARY

**Tags:** #tag1 #tag2
**Repo:** repo-name  (omit if not repo-scoped)

### Done
- consolidated [tool:dispatch_subagents.py] and [tool:manage-worktree.sh] into [dir:.agent/bin/] for [repo:el-capitan]
- fixed broken path in [file:.claude/hooks/mode-anchor.sh] — was calling [dir:.agent/tools/] which no longer exists

### Absorbed
- [concept:Mem0 memory extraction] — single-pass ADD-only, atomic fact indexing, entity linking for retrieval boosting
- [concept:Letta MemFS] — git-backed hot/cold tier split, sleep-time reflection subagent (https://docs.letta.com/letta-code/memory)

### Implemented
- [file:.agent/bin/get-diff.sh] — resolves base ref (upstream → origin → HEAD~1), exports BASE + DIFF_SOURCE
- [file:.agent/bin/dispatch_subagents.py] — fixed stderr reading, perspectives returns 0 on partial failure

### Promoted
- BSD tar ignores `**` glob patterns on macOS — use `--exclude=.env` not `--exclude=**/.env`
- Gate `git fetch` on FETCH_HEAD age to avoid blocking short sessions

### Open
- unresolved questions or follow-ups (omit section if empty)
```

**`### Promoted`** is the hot tier. Bullets here are appended to `~/.agent/PROFILE.md` as durable facts that persist across months and are always in-context for every agent. Use for constraints, workarounds, and patterns worth carrying forward permanently — not session-specific observations.

`### Raw session` (appended automatically by crew-log if SESSION.md is present) contains verbatim captured notes. Never summarize it; index it as-is.
