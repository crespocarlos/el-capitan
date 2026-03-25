# Journal Entry Schema

Reference for crew-log, crew-researcher, and crew-thinker. Entries are written to monthly files in `~/.agent/journal/YYYY-MM.md`.

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
**Hypothesis:** (optional) — what you expected before starting
**Decisions made:** key choices and why
**What broke / surprised me:** errors, wrong assumptions, corrections
**Outcome:** (optional) — fill after PR merges: did it work? any friction in review?
**Promote to rules:** conventions worth remembering, or "none"
```

### Learning entries (crew-researcher, crew-thinker)

```markdown
**Source:** URL, PR, repo, or concept
**Key idea:** single most important thing
**Hypothesis:** (optional) — what you expected this to teach you before reading/session
**Experiments queued:** things to build or try
**Outcome:** (optional) — what it actually taught you vs expectation; fill after experimenting
**Patterns emerging:** recurring themes across entries
```

### Pattern entries

```markdown
**Scope:** repo-name | global
**Rule:** actionable one-liner
**Context:** why this matters — what goes wrong without it, or what goes right with it
```
