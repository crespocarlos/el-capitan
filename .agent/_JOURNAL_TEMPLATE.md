# Journal Entry Schema

Reference for crew-log, crew-researcher, crew-thinker, and crew-remember. Entries are written to monthly files in `~/.agent/journal/YYYY-MM.md`.

## Unified Schema

Every entry has these shared fields:

```markdown
---
## DATE — SUMMARY

**Type:** engineering | learning | pattern
**Tags:** #tag1 #tag2
**What I learned:** transferable insight
**Connections:** links to previous entries or patterns, or "none"
**Open questions:** unresolved questions, or "none"
```

### Engineering entries (crew-log)

```markdown
**Repo:** repo-name
**Branch:** branch-name
**Files touched:** path/to/file.ts, path/to/other.ts
**What I did:** 1-2 sentences
**Decisions made:** key choices and why
**What broke / surprised me:** errors, wrong assumptions, corrections
**Promote to rules:** conventions worth remembering, or "none"
```

### Learning entries (crew-researcher, crew-thinker)

```markdown
**Source:** URL, PR, repo, or concept
**Key idea:** single most important thing
**Experiments queued:** things to build or try
**Patterns emerging:** recurring themes across entries
```

### Pattern entries (crew-remember)

```markdown
**Scope:** repo-name | global
**Rule:** actionable one-liner
**Context:** why this matters — what goes wrong without it, or what goes right with it
```
