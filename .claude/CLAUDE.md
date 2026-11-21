# Shared rules

Canonical rules live in `rules/` and are shared with Cursor. Claude Code reads no `alwaysApply` and
no globs, so a rule that must hold on every request is imported here as well as marked always-on;
without the import it is invisible to this harness.

Two rules stay glob-scoped, so importing them would charge every request for them: read
`typescript.mdc` before writing a `.ts` or `.tsx` file, and `crew-explorer-conventions.mdc` applies to code research; `voice.mdc` to
text published under Carlos's name.

@~/.cursor/rules/personal.mdc
@~/.cursor/rules/agent-output.mdc
@~/.cursor/rules/crew-router.mdc
@~/.cursor/rules/crew-orchestrator.mdc
@~/.cursor/rules/memory-capture.mdc
@~/.cursor/rules/prompt-engineering.mdc
@~/.cursor/rules/typescript.mdc

---

# el-capitan

Routing, workflows, and the pipeline state machine live in the imported rules; this file adds only
what is specific to this harness.

## Invocation

**Orchestrators** (`crew-reviewer`, `crew-specwriter`, `crew-pr-resolver`) run **inline in the main
session**: read `~/.claude/agents/crew-<name>.md` and execute it directly. Claude Code cannot nest
agent calls, so an orchestrator in a subagent cannot dispatch its personas.

For an explicit `crew <command>`, do not call Claude's `Skill` tool: read the routed
`~/.claude/skills/<name>/SKILL.md` and execute its workflow inline.

**Persona subagents** are dispatched by the orchestrator from the main session, each with its own
context window. Fallback priority when the Agent tool is unavailable: file-based `claude -p`
dispatch, then inline sequential runs (degraded: ordering bias) only when nothing else works.

Task state: resolve with `~/.agent/bin/crew-resolve-task-dir.py`.

<!-- el-capitan:memory -->
Claude Code and Cursor inject session memory at session start; other harnesses run `~/.agent/bin/crew-mem.py context --mode session` at task start. Follow `~/.cursor/skills/crew-memory/references/contract.md`.
<!-- /el-capitan:memory -->
