---
name: crew-diagnose
description: "Diagnose a Cursor or Claude transcript against the crew protocol. Use when the user asks why an agent run diverged, skipped a step, or misrouted, and supplies a transcript. Alias: 'crew diagnose <transcript>'."
---

# Diagnose

Find the first divergence between an agent transcript and the crew protocol.

Sources of truth: `~/.cursor/rules/crew-router.mdc` (routing) and `~/.cursor/rules/crew-orchestrator.mdc` (stages and gates). Read both before comparing.

1. Read the transcript JSONL at the path the user supplies. Claude Code JSONL contains `tool_use` and `tool_result` entries; use them as primary evidence of skipped steps, pushes before approval, and missing resolver calls. Cursor agent transcripts may omit them. If the file has no tool-call entries, rely on user and assistant text and add the `limit:` line to the report.
2. Map each `crew <command>` the user sent to its expected route and stage.
3. Walk the assistant turns in order. Mark the first turn that skips a stage, misroutes, or acts past a gate.
4. Report the first divergence:

```
divergence: <expected> vs <observed>
line: <transcript line>
likely-cause: <one line>
limit: tool calls not present in transcript   (only when no tool-call entries exist)
```

Do not report later divergences unless the user asks.
