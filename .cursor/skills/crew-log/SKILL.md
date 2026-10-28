---
disable-model-invocation: true
name: crew-log
description: "Log an agentic engineering session to the journal. Trigger: 'crew log'."
---

# Journal Entry

## When Invoked

Resolve context:

```bash
source ~/.agent/bin/task-env.sh
```

Read whatever is available: `$TASK_DIR/REPORT.md`, `$TASK_DIR/SESSION.md`, recent `git log -5 --format="%h %s"`. If no active task, synthesize from the current session conversation instead.

Show the draft and ask: **"Anything to add before I write this?"** If the user says nothing or "no", write immediately. Do not prompt for specific fields.

## Format

Write through `mem.py journal add`, with a prose body on stdin. The body is prose only: no heading, `**Tags:**`, `**Repo:**`, or `---` lines. Title, tags, scope, and date come from flags (`--date` defaults to today). The command stores one immutable observation per call in the unified memory store. Write in **prose paragraphs** — not bullets, not section headers. Each paragraph is one coherent idea and evidence for later consolidation. Write the "why", not just the "what".

```bash
~/.agent/bin/mem.py journal add --title "Title" --tags kibana mapping --repo <scope> <<'EOF'
First paragraph: what happened and why it matters.

Second paragraph (if there's a distinct second idea): another self-contained insight.
EOF
```

`<scope>` is the bare repository name (`kibana`); `OWNER/REPO` is normalized to it. Omit `--repo` for global entries. The command prints the observation ID.

## After writing

Keep the resulting observation IDs as evidence. Draft zero to three durable typed candidates into `~/.agent/memory/.inbox/`, citing those IDs; a no-op is valid. Show candidates with the entry and, only after approval, run `~/.agent/bin/mem.py import-inbox --all`. On exit 2 print `warning: memory unavailable`.

Then:
- If the entry contains a **durable rule** worth remembering in every future session, surface it: `"Worth adding to ~/.claude/CLAUDE.md?"`
- **Drift check** — only when `~/.claude/CLAUDE.md` holds inline preference text (it usually imports `personal.mdc` with `@`) and it differs from `rules/personal.mdc`, surface: `"Preferences have drifted — consider syncing."`
- If `TASK_DIR` is non-empty: clear `$TASK_DIR/SESSION.md` (buffer flushed).

## Plain-language gates

Show the full journal entry draft before writing — observations are immutable and there is no edit or delete.
