# Protocol map

Which file owns which rule, for judging whether a run diverged. Read a file before concluding a step
was skipped: a rule stated in one file and not another is not a divergence.

| File | What it controls |
|---|---|
| `rules/crew-router.mdc` | Trigger → crew member routing, dispatch mode, add-ons, routing invariants |
| `rules/crew-orchestrator.mdc` | Pipeline state machine, session-start awareness, autopilot, METRIC lines |
| `rules/personal.mdc` | Hard constraints, working style, research, engineering, testing, harness notes |
| `rules/agent-output.mdc` | Reply shape, labels, voice, artifact boundary |
| `rules/memory-capture.mdc` | When a memory candidate is proposed and how it is approved |
| `.cursor/agents/crew-specwriter.md` | Spec drafting protocol (Steps 1–6) |
| `.cursor/agents/crew-builder.md` | Implementation protocol and Completion Protocol |
| `.cursor/agents/crew-reviewer.md` | Multi-lens review orchestration; `references/` holds each step's detail |
| `.cursor/agents/specwriter-explorer.md`, `specwriter-scope.md`, `tester-explorer.md` | Exploration, scope critique, and test discovery for their orchestrator |
| `.cursor/skills/<name>/SKILL.md` | One command's workflow; `references/` holds material a step reads on demand |
| `.cursor/skills/spec-writing/references/*.md` | Spec and bug-spec templates (also `.agent/_*TEMPLATE.md`) |
| `.agent/tools/tools.json`, `TOOLS.md` | The command catalog and each tool's contract |
