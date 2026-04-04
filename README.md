# 🏴‍☠️ El Capitan

**A spec-driven AI engineering crew for Cursor and Claude Code.**

El Capitan gives you a team of coordinated AI agents that follow a structured pipeline — from drafting a spec to opening a pull request. You stay in control at two gates: you approve the spec before any code is written, and you approve the commit message before anything is pushed. Everything in between is automated.

Works in any git repository. All state lives outside your repos. No cloud sync, no vendor lock-in.

---

## Contents

- [How it works](#how-it-works)
- [Workflows](#workflows)
- [Quick start](#quick-start)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Command reference](#command-reference)
- [The crew](#the-crew)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Extending el-capitan](#extending-el-capitan)
- [License](#license)

---

## How it works

```mermaid
flowchart TB
    subgraph explore["explore"]
        direction LR
        research["🔬 crew-researcher"] -.-> think["💡 crew-thinker"]
        think -.-> journal[("📓 journal")]
        research -.-> journal
    end

    subgraph build["build"]
        direction LR
        issue["📝 create-issue"] -.->|"crew spec"| spec["📋 specwriter"]
        spec -->|"Gate 1: approve"| impl["🔨 builder"]
        impl -->|"auto"| bdiff["diff"]
        bdiff -->|"auto"| bcommit["commit"]
        bcommit -->|"Gate 2: approve"| openpr["open-pr"]
        openpr --> done(["PR opened"])
        impl -.->|"auto-recall"| journal2[("📓 journal")]
    end

    subgraph respond["respond"]
        direction LR
        resolver["🧩 pr-resolver"] --> rdiff["diff"]
        rdiff --> rcommit["commit"]
        rcommit --> pushed(["pushed"])
    end

    think -.->|"feeds into"| spec
    done -.->|"crew resolve PR"| resolver
    reviewer["🔍 reviewer"] -.->|"standalone"| impl
```

**Three workflows. Two explicit gates in `build`.** Run `crew autopilot` to advance automatically to the next gate, or drive each step manually — your choice.

El Capitan has three layers:

| Layer | File | Job |
|---|---|---|
| **Router** | `.cursor/rules/crew-router.mdc` | Maps `crew <command>` to the right handler |
| **Orchestrator** | `.cursor/rules/crew-orchestrator.mdc` | Pipeline state, session awareness, autopilot |
| **Runtime** | ralph, hooks, journal tools | Execution engines |

---

## Workflows

### `build` — build anything

Feature, bug fix, refactor, chore — the pipeline is the same. Crew-specwriter infers whether to use the standard or bug template from the content of your request.

```
crew start build                          # guided entry
crew spec https://github.com/org/repo/issues/123  # or spec directly from an issue
```

Stages: **spec → implement → diff → commit → open-pr**  
Terminal: PR opened as draft

### `respond` — respond to review comments

Fetches all unresolved review threads on an open PR, evaluates each one, proposes edits and replies, and resolves threads after your approval — in a single batch.

```
crew start review-cycle #456
crew resolve PR #456                      # same thing
```

Stages: **address-pr → diff → commit → push**  
Terminal: all threads resolved and pushed

### `explore` — think before building

Brainstorm, research a concept or a URL, connect ideas across your journal. No gates, no terminal condition. Use it to sharpen your thinking before starting a `build`.

```
crew brainstorm: what if we cached the API responses?
crew learn https://martinfowler.com/articles/feature-toggles.html
```

---

## Quick start

```bash
git clone git@github.com:crespocarlos/el-capitan.git ~/el-capitan
bash ~/el-capitan/install.sh
```

Then open any repository in Cursor or Claude Code and type:

```
crew start build
```

> All `crew` commands are typed into the AI chat, not the terminal.

---

## Prerequisites

### Required

| Dependency | Purpose | Install |
|---|---|---|
| [Cursor](https://cursor.com) or [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | The AI runtime | — |
| Git | Version control | `brew install git` |
| [GitHub CLI (`gh`)](https://cli.github.com) | Issues, PRs, GraphQL queries | `brew install gh && gh auth login` |
| `jq` | JSON processing in shell scripts | `brew install jq` |

### Optional — recommended

| Dependency | Purpose | Install |
|---|---|---|
| [ralph](https://github.com/simianhacker/ralph-loop) | Autonomous implementation loop — runs `crew implement` without holding a conversation open | See repo |
| [Ollama](https://ollama.ai) + `nomic-embed-text` | Local semantic search over your journal | `brew install ollama && ollama pull nomic-embed-text` |
| ChromaDB | Vector store for journal embeddings | `pip install chromadb ollama` |
| SemanticCodeSearch MCP | Semantic code search across the codebase inside Claude Code | `claude mcp add --scope user SemanticCodeSearch -- npx @elastic/semantic-code-search-mcp-server` |

> **Without ralph:** `crew implement` falls back to inline implementation — same tasks and checks, conversational rather than autonomous.  
> **Without Ollama + ChromaDB:** `crew recall` falls back to ripgrep full-text search.  
> **Without SemanticCodeSearch:** crew-specwriter uses file reads and grep for codebase exploration.

### macOS note

The notification hook (`osascript`, iTerm2 focus) is macOS-only. On other systems it exits silently — no configuration needed.

---

## Installation

```bash
git clone git@github.com:crespocarlos/el-capitan.git ~/el-capitan
bash ~/el-capitan/install.sh
```

`install.sh` creates symlinks from `~/.cursor/`, `~/.claude/`, and `~/.agent/tools/` back to `~/el-capitan`. No files are copied — updates to the repo are reflected immediately.

**To update:**

```bash
cd ~/el-capitan && git pull
bash install.sh
```

**To reinstall on a new machine:**

```bash
git clone git@github.com:crespocarlos/el-capitan.git ~/el-capitan
bash ~/el-capitan/install.sh
```

Task state and journal are not tracked by git — they live in `~/.agent/tasks/` and `~/.agent/journal/` and persist locally.

---

## Command reference

All commands start with `crew`. Type them in the AI chat — not your terminal.

### Build workflow

| Command | What it does |
|---|---|
| `crew start build` | Start a new build workflow (guided) |
| `crew spec <issue URL or #N>` | Draft a SPEC.md from a GitHub issue |
| `crew spec <plain description>` | Draft a SPEC.md from a description |
| `crew implement` | Select spec, create worktree, build |
| `crew diff` | Review the diff for issues before committing |
| `crew commit` | Propose and apply a semantic commit message |
| `crew open pr` | Push the branch and open a draft PR |

### Respond workflow

| Command | What it does |
|---|---|
| `crew start review-cycle #456` | Start a respond workflow |
| `crew resolve PR #456` | Fetch and action all unresolved review threads |

### Explore workflow

| Command | What it does |
|---|---|
| `crew brainstorm` | Interactive brainstorm session |
| `crew brainstorm: <topic>` | Start brainstorm with a specific topic |
| `crew learn <concept or URL>` | Fetch, distill, and teach a concept — writes to journal |

### Pipeline & session

| Command | What it does |
|---|---|
| `crew autopilot` | Auto-advance from current state to next gate |
| `crew status` | Print current pipeline state and active workflow |
| `crew health` | Run setup health checks (symlinks, tools, auth) |
| `crew abandon` | Gracefully abandon the current task |

### Review & quality

| Command | What it does |
|---|---|
| `crew review` | Multi-lens self-review of your branch diff |
| `crew review PR #456` | Multi-lens review of someone else's PR |
| `crew review spec` | Multi-lens review of the active SPEC.md |

### Memory & journal

| Command | What it does |
|---|---|
| `crew log` | Record the session to the engineering journal |
| `crew recall: <question>` | Search the journal by meaning or keyword |

### Utilities

| Command | What it does |
|---|---|
| `crew create issue: <description>` | Structure a rough idea into a GitHub issue and file it |
| `crew cleanup` | Remove stale worktrees, branches, and task directories |
| `crew migrate` | Migrate old-layout task state to UUID layout |

> **Aliases:** `crew start build` = `crew spec`. `crew start review-cycle` = `crew resolve PR`.  
> `crew address PR` still works but is deprecated — use `crew resolve PR`.

---

## The crew

7 orchestrator agents, 13 persona subagents, 9 skills.

**Orchestrators** dispatch persona subagents in parallel for multi-lens analysis. **Skills** run inline for interactive pipeline steps. All agents are markdown files — readable, editable, version-controlled.

### 📋 crew-specwriter

Drafts a `SPEC.md` from a GitHub issue or plain description. Explores the codebase for existing patterns, drafts acceptance criteria tight enough for autonomous implementation, then runs a silent three-way critique (scope, adversarial, implementer personas) before presenting the result.

- Automatically selects the standard or bug spec template based on the content of your request — no flag needed
- Critiques cover: scope creep, missing edge cases in AC, implementation ambiguity
- Stops at Gate 1 — waits for your approval before any code is written

**Persona subagents:** `specwriter-scope`, `specwriter-adversarial`, `specwriter-implementer`

**Skills:** `crew-create-issue`, `crew-implement`, `crew-diff`, `crew-commit`, `crew-open-pr`, `crew-cleanup`, `crew-abandon`

### 🔨 crew-builder

The implementation engine. Reads a SPEC.md, works through each task in order, runs per-task acceptance checks, and writes a REPORT.md. Launched by `crew implement`, which handles worktree setup, spec selection, and pattern auto-recall.

- Supports two modes: **ralph** (autonomous loop) or **inline** (conversational, same protocol)
- Per-task acceptance checks run before marking each task done
- Hands back a REPORT.md — all pass/fail results, changed files

### 🔍 crew-reviewer

Multi-lens review of a branch diff, a PR, or a SPEC.md. Dispatches five reviewer personas in parallel and consolidates findings into a single prioritized report.

**Personas:** Code Quality, Adversarial, Fresh Eyes, Architecture, Product Flow  
**Modes:** `crew review` (self), `crew review PR #N` (others), `crew review spec`

### 🧩 crew-pr-resolver

Processes all unresolved review threads on a PR in a single batch: evaluates each thread, proposes edits and reply text, and applies only what you approve. Handles Apply, Adapt, Reject, Defer, and Already Addressed verdicts. Never touches resolved or outdated threads.

### 🔬 crew-researcher

Fetches a URL, GitHub PR, or concept name — distills what matters and writes a journal entry. Feeds naturally into `crew brainstorm` after teaching.

### 💡 crew-thinker

Two modes:
- **Pipeline** — dispatches 4 thinking personas in parallel (builder, contrarian, connector, pragmatist), consolidates tensions and opportunities into a report
- **Brainstorm** — interactive back-and-forth, unlimited turns; can offer to draft a SPEC when an idea solidifies

**Persona subagents:** `thinker-builder`, `thinker-contrarian`, `thinker-connector`, `thinker-pragmatist`

**Skills:** `crew-log`, `crew-recall`

---

## Architecture

### File layout

```
el-capitan/
├── .cursor/
│   ├── rules/               # Always-loaded orchestration rules (.mdc)
│   │   ├── crew-orchestrator.mdc   # Pipeline state machine (always loaded)
│   │   ├── crew-router.mdc         # Routing table (always loaded)
│   │   ├── crew-autopilot.mdc      # Autopilot logic (on-demand)
│   │   └── crew-health.mdc         # Health checks (on-demand)
│   ├── agents/              # Agent protocols (.md)
│   │   ├── crew-*.md               # Orchestrator agents
│   │   ├── reviewer-*.md           # Reviewer personas
│   │   ├── specwriter-*.md         # Specwriter personas
│   │   └── thinker-*.md            # Thinker personas
│   └── skills/              # Inline skill protocols
│       └── crew-<name>/SKILL.md
├── .claude/
│   ├── CLAUDE.md            # Claude Code session instructions (always loaded)
│   ├── hooks/               # PostToolUse, Notification, SessionStart hooks
│   └── settings.json        # Hook configuration
├── .agent/
│   ├── tools/               # Shell scripts and Python utilities
│   ├── scripts/             # Fallback dispatch scripts (bash)
│   ├── queries/             # GraphQL query files
│   ├── _SPEC_TEMPLATE.md    # Standard spec template
│   └── _BUG_SPEC_TEMPLATE.md  # Bug spec template
└── install.sh               # Symlink installer
```

### State layout (outside the repo)

```
~/.agent/
├── PROFILE.md               # Your personal context (never tracked by git)
├── journal/                 # Monthly engineering journal entries
├── vectorstore/             # ChromaDB embeddings (auto-created)
├── tools/                   # Symlinked from el-capitan
├── scripts/                 # Symlinked from el-capitan
├── queries/                 # Symlinked from el-capitan
└── tasks/<uuid>/            # Per-task state: SPEC.md, PROGRESS.md, SESSION.md, REPORT.md
    └── .task-id             # JSON: uuid, repo_remote_url, branch, slug, created_at
```

Task state is keyed by UUID and resolved via `.task-id` lookup against the current `git remote + branch`. Multiple specs can coexist per branch. Completed tasks are never deleted automatically.

### Context budget

Always-loaded context is kept minimal on purpose:

| File | Lines | Loaded |
|---|---|---|
| `crew-orchestrator.mdc` | ~161 | Every session |
| `crew-router.mdc` | ~59 | Every session |
| `CLAUDE.md` | ~63 | Every session |
| `crew-autopilot.mdc` | ~51 | Only when `crew autopilot` is invoked |
| `crew-health.mdc` | ~88 | Only when `crew health` is invoked |

Orchestrator agents (crew-specwriter, crew-reviewer, etc.) and skill files are loaded per-command, not globally. Fallback dispatch blocks for degraded environments live in `.agent/scripts/` — not in agent files.

---

## Configuration

### PROFILE.md

`~/.agent/PROFILE.md` is your personal context file. It persists across sessions and machines, is never tracked by git, and is read by `crew brainstorm`, `crew thinker` (pipeline mode), and optionally `crew spec`.

Fill it with anything that helps the agents work in your context:

```markdown
# Profile

**Role:** Senior engineer, platform team
**Current project:** Event pipeline for real-time analytics
**Stack:** TypeScript, Node.js, Kafka, PostgreSQL
**Preferences:** Explicit error types, no magic globals, prefer composition over inheritance
**Recurring context:** All new behavior must be behind a feature flag (LaunchDarkly)
```

A starter template is created at `~/.agent/PROFILE.md` on first install.

### Claude Code hooks

Project-level hooks in `.claude/settings.json` run automatically:

| Hook | Trigger | What it does |
|---|---|---|
| `PostToolUse` | Every Bash/Write/Edit call | Logs to `~/.agent/telemetry/` as JSONL |
| `Notification` | Claude needs input | macOS notification + iTerm2 focus |
| `SessionStart` | Session begins | Logs session start time |

Hooks exit 0 on error — they never block the agent. Telemetry is local-only.

### Autopilot

`crew autopilot` chains from the current pipeline state to the next gate:

- From **APPROVED**: implement → diff → commit *(stops at Gate 2)*
- From **IMPLEMENTING**: diff → commit *(stops at Gate 2)*
- From **COMMITTING** (after Gate 2 approval): open PR → done

Autopilot never skips a gate and never auto-retries on failure. If a step fails, it stops and surfaces the error.

### Semantic journal search

After indexing, `crew recall` supports natural-language queries:

```bash
# Index your journal
journal-search.py index

# Then in chat:
crew recall: how did we handle the retry logic in kibana?
```

Without Ollama + ChromaDB, `crew recall` falls back to ripgrep full-text search — still useful, just not semantic.

---

## Extending el-capitan

### Add a custom skill

1. Create `~/.cursor/skills/<name>/SKILL.md` with a `## Protocol` section
2. Add a routing entry to `~/.cursor/rules/crew-router.mdc`
3. Regular files (not symlinks) are treated as add-ons and never overwritten by `install.sh`

### Add a custom agent

1. Create `~/.cursor/agents/<name>.md` with YAML frontmatter:
   ```yaml
   ---
   name: my-agent
   description: "What it does and when to trigger it."
   ---
   ```
2. Add a routing entry to `~/.cursor/rules/crew-router.mdc`

### Identify add-ons vs core

```bash
# Symlinks = core (managed by el-capitan), regular files = your add-ons
find ~/.cursor/agents ~/.cursor/skills -maxdepth 2 -name '*.md' ! -type l
```

### Update routing in both files

When adding a command, update **both** routing files — they must stay in sync:

- `.cursor/rules/crew-router.mdc` — authoritative routing table
- `.claude/CLAUDE.md` — Claude Code session copy

`install.sh` has a comment reminding you of this.

---

## License

[MIT](LICENSE)
