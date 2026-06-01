---
name: crew-log
description: "Log an agentic engineering session to the journal. Trigger: 'crew log'."
---

# Journal Entry

## When Invoked

Resolve context:

```bash
MONTH=$(date +%Y-%m)
JOURNAL_FILE=~/.agent/journal/$MONTH.md
TASK_DIR=$(~/.agent/bin/resolve-task-dir.py 2>/dev/null || echo "")
```

Read whatever is available: `$TASK_DIR/REPORT.md`, `$TASK_DIR/SESSION.md`, recent `git log -5 --format="%h %s"`. If no active task, synthesize from the current session conversation instead.

Show the draft and ask: **"Anything to add before I write this?"** If the user says nothing or "no", write immediately. Do not prompt for specific fields.

## Format

Append to `$JOURNAL_FILE` (create if missing). Write in **prose paragraphs** — not bullets, not section headers. Each paragraph is one coherent idea, self-contained enough to be retrieved in isolation months later. Write the "why", not just the "what".

```markdown
---

## DATE — TITLE

**Tags:** #tag1 #tag2
**Repo:** repo-name  (omit if not repo-scoped)

First paragraph: what happened and why it matters.

Second paragraph (if there's a distinct second idea): another self-contained insight.
```

Use `$(date +%Y-%m-%d)`. Never modify existing entries — append only.

## After writing

Index the entry:

```bash
~/.agent/bin/journal-search.py add "$JOURNAL_FILE" --entry "$(date +%Y-%m-%d)"
```

Then:
- If the entry contains a **durable rule** worth remembering in every future session, surface it: `"Worth adding to ~/.claude/CLAUDE.md?"`
- **Drift check** — if `~/.claude/CLAUDE.md` and `~/.cursor/rules/personal.mdc` differ in substance, surface: `"Preferences have drifted — consider syncing."`
- If `TASK_DIR` is non-empty: clear `$TASK_DIR/SESSION.md` (buffer flushed).

## Auto-clarity override

Show the full journal entry draft before writing — entries are append-only and there is no delete.
