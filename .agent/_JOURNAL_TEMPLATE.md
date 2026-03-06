# Journal Entry Schema

Reference for crew-journal and crew-creative. Entries are written to monthly files in `~/.agent/journal/YYYY-MM.md`.

## Unified Schema

Every entry has these shared fields:

```markdown
---
## DATE — SUMMARY

**Type:** engineering | learning
**Tags:** #tag1 #tag2
**What I learned:** transferable insight
**Connections:** links to previous entries or patterns, or "none"
**Open questions:** unresolved questions, or "none"
```

### Engineering entries (crew-journal)

```markdown
**Repo:** repo-name
**Branch:** branch-name
**Files touched:** path/to/file.ts, path/to/other.ts
**What I did:** 1-2 sentences
**Decisions made:** key choices and why
**What broke / surprised me:** errors, wrong assumptions, corrections
**Promote to rules:** conventions for CLAUDE.md / AGENTS.md, or "none"
```

### Learning entries (crew-creative)

```markdown
**Source:** URL, PR, repo, or concept
**Key idea:** single most important thing
**Experiments queued:** things to build or try
**Patterns emerging:** recurring themes across entries
```
