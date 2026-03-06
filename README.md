# el-capitan

A portable personal agentic engineering orchestrator for Cursor and Claude Code.

el-capitan is a crew of AI agents and skills that handle the repetitive parts of engineering work — speccing, reviewing, committing, handling PR feedback, learning — so you can focus on the two decisions that matter: **approving the spec** and **merging the PR**.

## How it works

```mermaid
flowchart TD
    subgraph learning ["Learning Lane"]
        learn["ae-learn\nfetch + teach"]
        creative["ae-creative\nconnect · apply · challenge"]
        learn -->|"want ideas?"| creative
    end

    subgraph engineering ["Engineering Lane"]
        spec["ae-spec\ndraft SPEC.md"]
        approve(["🧑 YOU: approve spec"])
        implement["implement"]
        diffcheck["ae-diff-check\nreview local diff"]
        commit["ae-commit\nsemantic commit"]
        propen["ae-pr-open\npush + open PR"]
        resolver["ae-pr-resolver\nhandle all open threads"]
        merge(["🧑 YOU: merge"])
    end

    subgraph review ["Review Lane"]
        prreview["ae-pr-review\ndeep-review someone's PR"]
        eval["ae-pr-comments-eval\nevaluate single suggestion"]
    end

    journal["ae-journal\nlog session — any time"]
    journalmd[("JOURNAL.md")]

    creative -->|"idea → task"| spec
    spec --> approve --> implement --> diffcheck --> commit --> propen --> resolver --> merge

    prreview -.->|"standalone"| prreview
    eval -.->|"standalone"| eval
    resolver -->|"per comment"| eval

    merge --> journal
    journal --> journalmd
    creative --> journalmd
    journal -->|"what did I learn?"| creative
```

**You appear at two gates only.** Everything between runs autonomously.

## Crew

| Name | Type | What it does |
|------|------|-------------|
| **ae-spec** | agent | Fetches a GitHub issue, explores the codebase, drafts a SPEC.md with acceptance criteria |
| **ae-diff-check** | skill | Scans `git diff` for type safety issues, missing tests, pattern violations |
| **ae-commit** | skill | Reads diff + SPEC.md, proposes a conventional commit message, waits for approval |
| **ae-pr-open** | skill | Pushes branch, generates PR description from SPEC.md + commits, opens the PR |
| **ae-pr-review** | skill | Deep-reviews someone else's PR — reads full files, traces impact, verifies tests |
| **ae-pr-resolver** | agent | Fetches all unresolved PR threads on your PR, processes each one (apply/adapt/reject/defer) |
| **ae-pr-comments-eval** | skill | Evaluates a single code suggestion from any source (reviewer, Copilot, colleague) |
| **ae-journal** | skill | Logs an engineering session — 3 questions, appends to JOURNAL.md, surfaces CLAUDE.md candidates |
| **ae-learn** | agent | Fetches a URL, PR, repo, or concept and teaches you what matters |
| **ae-creative** | agent | Connects learning to past sessions, generates ideas, pushes back on assumptions |

### PR crew — three members, three directions

- **ae-pr-review** — you review someone else's code (outbound review)
- **ae-pr-resolver** — someone reviewed your code, handle their feedback (inbound batch)
- **ae-pr-comments-eval** — evaluate a single suggestion from any source (inline)

## Pipeline

```
ae-spec → [approve] → implement → ae-diff-check → ae-commit → ae-pr-open → ae-pr-resolver → [merge]
```

When a gate fails:
- **Spec rejected** — revise and re-present
- **Diff check finds issues** — fix, then re-run
- **PR comments need input** — surface to user, wait, resume

## Task state

Task files live outside any repo at `~/.agent/tasks/<repo>/<branch>/`:

```
~/.agent/
├── _SPEC_TEMPLATE.md          ← reusable template
├── JOURNAL.md                  ← append-only session log
└── tasks/
    └── kibana/                 ← auto-derived from git
        ├── feat-retry-logic/
        │   ├── SPEC.md
        │   └── PROGRESS.md
        └── fix-flaky-test/
            └── SPEC.md
```

Path resolved automatically:
```bash
~/.agent/tasks/$(basename $(git rev-parse --show-toplevel))/$(git branch --show-current)/
```

## Add-ons

Core crew ships with el-capitan (installed as symlinks). Add-ons are skills or agents you drop directly into `~/.cursor/agents/` or `~/.cursor/skills/` as regular files — no changes to el-capitan needed.

```bash
# See what's installed — symlinks = core, regular files = add-ons
find ~/.cursor/agents ~/.cursor/skills -maxdepth 2 -type f -name '*.md' ! -type l
```

The orchestrator discovers add-ons at runtime and routes to them by matching triggers to their description frontmatter.

## Install

```bash
git clone git@github.com:carloscrespo/el-capitan.git ~/el-capitan
bash ~/el-capitan/install.sh
```

New machine = clone + install. All agents, skills, rules, templates, and journal restored via symlinks. `~/.agent/tasks/` starts empty — task state is ephemeral per machine.

## File layout

```
~/el-capitan/                            ← git repo (portable)
├── install.sh
├── README.md
├── .claude/
│   └── CLAUDE.md                        ← agent context for Claude Code
├── .cursor/
│   ├── rules/
│   │   ├── ae-orchestrator.mdc          ← crew manifest (always on)
│   │   └── ae-learn.mdc                 ← learning router
│   ├── agents/
│   │   ├── ae-spec.md
│   │   ├── ae-learn.md
│   │   ├── ae-creative.md
│   │   └── ae-pr-resolver.md
│   └── skills/
│       ├── ae-commit/SKILL.md
│       ├── ae-diff-check/SKILL.md
│       ├── ae-journal/SKILL.md
│       ├── ae-pr-comments-eval/SKILL.md
│       ├── ae-pr-open/SKILL.md
│       └── ae-pr-review/
│           ├── SKILL.md
│           └── references/
│               ├── commands.md          ← gh commands, consumer-finding patterns
│               └── review-patterns.md   ← review dimensions, size-based strategy
└── .agent/
    ├── _SPEC_TEMPLATE.md
    └── JOURNAL.md
```

## Design decisions

**Skills vs agents.** Skills are stateless instructions the main agent follows inline — good for single-purpose tasks (commit, diff check, journal). Agents are autonomous subagents launched as separate processes — good for multi-step tasks that fetch data and make decisions (spec, learn, PR resolution).

**Skills with references.** Complex skills like ae-pr-review use a `references/` directory for command patterns and review frameworks. This keeps the main SKILL.md workflow-focused while providing concrete commands the agent reads when needed. Inspired by the [artifact analysis patterns](https://github.com/carloscrespo/el-capitan/blob/main/.cursor/skills/ae-pr-review/references/review-patterns.md) approach.

**Symlinks, not copies.** `install.sh` creates per-file symlinks from `~/.cursor/` into the repo. This means core crew members are always in sync with the repo, while add-ons (regular files) live alongside without being tracked.

**No second-opinion agent.** Consulting a different model (Gemini, etc.) for a second take is occasionally useful, but not frequently enough to justify a crew member. When needed, run the CLI directly. If model diversity proves consistently valuable, the right move is adding it as a step inside ae-spec or ae-pr-review, not as a standalone agent.

**JOURNAL.md is portable, tasks/ is not.** The journal captures cross-session learning and is symlinked from the repo. Task state (SPEC.md, PROGRESS.md) is ephemeral and machine-local — different machines may have different branches checked out.

**Review dimensions from CodeRabbit.** ae-pr-review's [review patterns](https://github.com/carloscrespo/el-capitan/blob/main/.cursor/skills/ae-pr-review/references/review-patterns.md) use CodeRabbit's six review categories (functional correctness, stability, performance, data integrity, security, maintainability) as the scanning framework, but focus depth on what automated tools miss: intent mismatches, cross-component impact, and completeness gaps.
