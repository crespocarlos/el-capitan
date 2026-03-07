# el-capitan

Your engineering crew, orchestrated. Spec it, build it, ship it — you just approve.

el-capitan is a portable system of AI agents and skills for [Cursor](https://cursor.com) and [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that handles speccing, implementing, reviewing, committing, and PR management. You make four decisions: **approve the spec**, **approve the commit**, **approve the PR**, and **merge**.

## Quick start

```bash
git clone git@github.com:crespocarlos/el-capitan.git ~/el-capitan
bash ~/el-capitan/install.sh
```

Then, in any repo:

```
crew spec https://github.com/org/repo/issues/123
```

## Usage

All commands start with `crew`. Explicit routing only — no guessing.

### Pipeline

| Command | What it does |
|---|---|
| `crew spec https://github.com/org/repo/issues/123` | Draft a SPEC.md from an issue |
| `crew implement` | Create worktree + build from SPEC |
| `crew diff` | Review the local diff |
| `crew commit` | Propose a semantic commit message |
| `crew open pr` | Push + open a draft PR |
| `crew address PR #456` | Handle open review comments |

### Standalone

| Command | What it does |
|---|---|
| `crew review PR #456` | Deep-review someone else's PR |
| `crew eval: reviewer says use retry() instead` | Evaluate a single code suggestion |
| `crew learn git worktrees` | Fetch + teach a concept |
| `crew learn https://article.com/post` | Fetch + teach from a URL |
| `crew brainstorm` | Creative session — connect ideas, challenge assumptions |
| `crew brainstorm: what if we cached the API responses?` | Interactive brainstorm on a topic |
| `crew log` | Log the engineering session to the journal |
| `crew recall: how do we handle retries in kibana?` | Search journal by meaning |
| `crew remember: always use data-test-subj for selectors` | Persist a pattern with embeddings |

## How it works

```mermaid
flowchart TD
    subgraph engineering ["Engineering"]
        spec["crew-specwriter"]
        approve(["YOU: approve"])
        implement["crew-implement"]
        diff["crew-diff"]
        commit["crew-commit"]
        approveCommit(["YOU: approve"])
        openpr["crew-open-pr"]
        approvePR(["YOU: approve"])
        merge(["YOU: merge"])
    end

    subgraph reviewCycle ["Review Cycle"]
        waiting(["waiting for reviews"])
        resolver["crew-pr-resolver"]
        waiting -->|"comments arrive"| resolver
        resolver -->|"resolved"| waiting
    end

    subgraph learning ["Learning"]
        researcher["crew-researcher"]
        thinker["crew-thinker"]
        researcher -->|"want ideas?"| thinker
    end

    subgraph memory ["Memory"]
        log["crew-log"]
        recall["crew-recall"]
        remember["crew-remember"]
        journalFiles[("journal/")]
    end

    spec --> approve --> implement --> diff --> commit
    commit --> approveCommit --> openpr
    openpr --> approvePR --> reviewCycle --> merge

    merge --> log
    log --> journalFiles
    researcher --> journalFiles
    thinker --> journalFiles
    recall -->|"semantic search"| journalFiles
    remember --> journalFiles
    implement -.->|"auto-recall"| journalFiles
```

**Four gates. Everything between runs autonomously.**

## The crew

### Engineering

| Name | Type | What it does |
|------|------|-------------|
| **crew-specwriter** | agent | Fetches a GitHub issue, explores the codebase, drafts a SPEC.md with acceptance criteria |
| **crew-implement** | skill + agent | Gates, spec selection, worktree creation, auto-recall. Launches `@crew-builder` for implementation. |
| **crew-diff** | skill | Scans `git diff` for type safety, missing tests, pattern violations. Auto-recalls repo patterns. |
| **crew-commit** | skill | Proposes a conventional commit message, waits for approval |
| **crew-open-pr** | skill | Pushes branch, generates PR description, opens a draft PR. Fork-aware. |

### Review

| Name | Type | What it does |
|------|------|-------------|
| **crew-pr-reviewer** | agent | Deep-reviews someone else's PR — full files, impact tracing, test verification |
| **crew-pr-resolver** | agent | Fetches all unresolved threads on your PR, processes each (apply/adapt/reject/defer) |
| **crew-eval-pr-comments** | skill | Evaluates a single suggestion. Presents verdict for approval before acting. |

### Learning

| Name | Type | What it does |
|------|------|-------------|
| **crew-researcher** | agent | Fetches a URL, PR, repo, or concept and teaches you what matters. Writes to journal. |
| **crew-thinker** | agent | Connects ideas, generates experiments, challenges assumptions. Pipeline or brainstorm mode. |

### Memory

| Name | Type | What it does |
|------|------|-------------|
| **crew-log** | skill | Logs an engineering session — auto-gathers context, writes to monthly journal |
| **crew-recall** | skill | Searches journal by meaning (semantic) or metadata (grep) |
| **crew-remember** | skill | Persists patterns to journal with embeddings. Optional escalation to CLAUDE.md / AGENTS.md. |

## Key features

### Worktree-first

`crew implement` creates a git worktree with a conventional branch (`feature/`, `bugfix/`, etc.) so implementation happens in an isolated directory. `crew-pr-resolver` resolves to the correct worktree before applying changes. Main stays clean.

### Journal-based memory

Patterns, conventions, and learnings live in `~/.agent/journal/` as monthly markdown files with local embeddings. Key crew members auto-recall repo-specific patterns at session start — no manual config needed.

### Local semantic search

Optional but powerful. Uses [Ollama](https://ollama.ai) + ChromaDB — everything stays on your machine.

```bash
ollama pull nomic-embed-text
pip install chromadb ollama
journal-search index
```

Without these, everything works — `crew-recall` falls back to ripgrep.

### Add-ons

Drop custom agents or skills into `~/.cursor/agents/` or `~/.cursor/skills/` as regular files. The orchestrator discovers them at runtime.

```bash
# Symlinks = core (el-capitan), regular files = your add-ons
find ~/.cursor/agents ~/.cursor/skills -maxdepth 2 -type f -name '*.md' ! -type l
```

## Task state

All task data lives outside any repo at `~/.agent/`:

```
~/.agent/
├── PROFILE.md              ← your context (optional, gitignored)
├── journal/                ← monthly entries with embeddings
├── vectorstore/            ← ChromaDB data (auto-created)
├── tools/journal-search    ← semantic search CLI
└── tasks/<repo>/<branch>/  ← SPEC.md, PROGRESS.md, SESSION.md
```

Path resolved automatically from git state. Journal and profile are private — never tracked by git.

## Prerequisites

| Requirement | Required? |
|---|---|
| [Cursor](https://cursor.com) or [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | Yes |
| Git + [GitHub CLI (`gh`)](https://cli.github.com) | Yes |
| Python 3.9+ | For semantic search |
| [Ollama](https://ollama.ai) + `nomic-embed-text` | Optional |
| `pip install chromadb ollama` | Optional |

## Install

```bash
git clone git@github.com:crespocarlos/el-capitan.git ~/el-capitan
bash ~/el-capitan/install.sh
```

New machine = clone + install. Everything restored via symlinks. Task state starts empty. Journal and profile persist locally.

## License

[MIT](LICENSE)
