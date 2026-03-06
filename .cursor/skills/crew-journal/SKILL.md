---
name: crew-journal
description: "Log an agentic engineering session to the journal. Use when the user says 'journal', 'log this', 'end of session', or asks to record what happened. Triggerable any time."
---

# Journal Entry

## When Invoked

Ask the user three questions (use the AskQuestion tool if available, otherwise ask inline):

1. **What did you delegate or work on?** — tasks, issues, PRs
2. **What broke, surprised you, or needed correction?** — agent mistakes, missing context, wrong assumptions
3. **Anything to add to CLAUDE.md?** — conventions learned, gotchas discovered, patterns to enforce

## Write the Entry

Append a dated entry to `~/.agent/JOURNAL.md`:

```bash
cat >> ~/.agent/JOURNAL.md << 'ENTRY'

---
## <DATE> — <ONE LINE SUMMARY>

**Type:** engineering
**Delegated:** <answer to Q1>
**Broke/Surprised:** <answer to Q2>
**CLAUDE.md candidates:** <answer to Q3, or "none">
ENTRY
```

Replace placeholders with actual content. Use `$(date +%Y-%m-%d)` for the date.

## After Writing

1. If the user provided CLAUDE.md candidates, surface them:
   > "These items look ready for CLAUDE.md: [list]. Want me to add them now?"

2. Always offer the creative handoff:
   > "Want @crew-creative to connect this session to past patterns and generate ideas?"

## Notes

- Keep entries concise — 2-3 sentences per answer max
- Triggerable any time: after implementation, after PR review, after learning, after support investigation, or just at end of day
- Never modify existing journal entries — only append
- Engineering entries use `**Type:** engineering`; learning entries (written by @crew-creative) use `**Type:** learning`
