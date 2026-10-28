---
name: crew-diagnose
description: "Diagnose a Cursor or Claude transcript against the crew protocol. Use when the user asks why an agent run diverged, skipped a step, or misrouted, and supplies a transcript. Alias: 'crew diagnose <transcript>'."
---
# Diagnose

Read the transcript JSONL, compare observed crew protocol events against expected routing and stages, report the first divergence with line evidence and likely cause.
