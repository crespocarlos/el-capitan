# Shared rules

Canonical rules live in `rules/` and are shared with Cursor. Claude Code reads no `alwaysApply` and
no globs, so an always-on rule is imported here; a scoped rule or skill gets a one-line pointer.
`crew-explorer-conventions.mdc` applies to code research, `voice.mdc` to text published under
Carlos's name.

Read ~/.cursor/rules/typescript.mdc before writing a .ts or .tsx file.
Read ~/.cursor/skills/prompt-authoring/SKILL.md before the work its description names.

@~/.cursor/rules/personal.mdc
@~/.cursor/rules/agent-output.mdc
@~/.cursor/rules/crew-router.mdc
@~/.cursor/rules/crew-orchestrator.mdc
@~/.cursor/rules/memory-capture.mdc

---

# el-capitan

Routing, workflows and the pipeline state machine live in the imported rules; this file adds only
harness specifics.

## Invocation

**Orchestrators** (`crew-reviewer`, `crew-specwriter`) run inline in the main session: read
`~/.claude/agents/crew-<name>.md` and execute it. Claude Code cannot nest agent calls, so an
orchestrator in a subagent cannot dispatch its personas. `crew-pr-resolver`: the router's Dispatch.

For an explicit `crew <command>`, do not call Claude's `Skill` tool: read the routed
`~/.claude/skills/<name>/SKILL.md` and execute its workflow inline.

**Personas** are dispatched by the orchestrator from the main session, each with its own context
window. Without the Agent tool, fall back to file-based `claude -p` dispatch, then to inline
sequential runs (degraded: ordering bias).

Task state: resolve with `~/.agent/bin/crew-resolve-task-dir.py`.

<!-- el-capitan:memory -->
Claude Code and Cursor inject session memory at session start; other harnesses run `~/.agent/bin/crew-mem.py context --mode session` at task start. Follow `~/.cursor/skills/crew-memory/references/contract.md`.
<!-- /el-capitan:memory -->
