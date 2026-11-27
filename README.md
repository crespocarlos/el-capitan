# El Capitan

A spec-driven engineering pipeline for Cursor and Claude Code: a written spec, a multi-lens review and a commit gate around the AI agent you already use.
You approve the spec before any code is written (Gate 1) and the pull request before anything is pushed (Gate 2); the steps between run on their own.
It works in any git repository, keeps its state in `~/.agent` outside your repositories, and syncs nothing to a cloud service.

## Quick start

```bash
git clone https://github.com/crespocarlos/el-capitan.git ~/el-capitan
bash ~/el-capitan/install.sh
```

Or let the installer clone for you:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/crespocarlos/el-capitan/main/install.sh)"
```

Run this way, it clones to `${EL_CAPITAN_HOME:-~/el-capitan}` and re-runs from there; an existing
checkout there is reused as it is. Before writing anything it checks for `python3` 3.9 or newer,
`git`, `gh` and `jq`, and refuses with one line when one is missing.

Then open any repository in Cursor or Claude Code and type, in the AI chat (not the terminal):

```
crew spec <issue URL or description>
```

## Everyday commands

Every command is typed into the AI chat. `crew help` prints these tables.

<!-- generated:commands (crew-lint.py --write-readme) -->
| Command | What it does |
|---|---|
| `crew spec` issue/URL/description | Draft a SPEC.md, then stop at Gate 1 for approval. |
| `crew implement` | Orchestrate implementation of an approved SPEC.md. |
| `crew commit` | Generate a semantic commit message and commit. |
| `crew open pr` | Push the current branch and open a PR with a generated description. |
| `crew review address` | Work through findings from the most recent crew review inline. |
| `crew review` [PR #X \| spec \| idea \| changes \| (self)] | Multi-lens review of code, a PR, a spec or an idea. |
| `crew pr` view\|diff\|repo\|issue | Read a PR, its diff, the repository or an issue through one read-only tool; writes stay `gh`. |
| `crew resolve PR` #X or URL | Read-only analysis of unresolved PR review comments; returns a plan of verdicts, edits and replies. |
| `crew log` | Log an agentic engineering session to the journal. |
| `crew memory` add text\|seed\|consolidate\|journal | Add a durable lesson to memory, draft candidates from the journal, consolidate the inbox, or import legacy journals. |
| `crew create issue` description | Structure a rough idea into a well-formed GitHub issue and file it. |
| `crew evals` | Inspect, compare and explain evaluation experiments and scores (Kibana repositories only). |
| `crew e2e` [PR\|status\|setup] | Start and read a nightshift e2e run for a PR on demand: real browser/API tests of a deployed Kibana PR. |
| `crew handoff` [resume] | Save or resume working state across a context reset or a new session. |
| `crew ls` [--all] [--repo R] [--status S] | Task table for the current repo (`--repo all` for every one); IMPLEMENTING tasks idle for 14 days fold into one stale line. |
| `crew report` [--since 30d] [--repo R] | Tasks opened and closed, review verdicts, findings by label and fixed rate, stage costs and durations, tool failures. |
| `crew doctor` | One screen of install health: links, hook registrations, managed blocks, tool versions, `gh` sign-in, state sizes; exit 1 on a problem. |
| `crew gc` [--apply] | Retention from `~/.agent/config.json`: artifacts of DONE tasks after 14 days, DONE tasks archived after 90, session files after 30, the legacy telemetry; a dry run unless `--apply`. |
| `crew help` | List every crew command and what it does, generated from the router and tools.json. |
<!-- /generated:commands -->

The build workflow is `crew spec`, `crew implement`, `crew review`, `crew commit`, `crew open pr`;
the respond workflow is `crew resolve PR #456`. [Architecture](docs/architecture.md) walks through
both.

### Standalone

Not a pipeline stage; run it when you need it.

<!-- generated:standalone (crew-lint.py --write-readme) -->
| Command | What it does |
|---|---|
| `crew idp` | Quarterly: draft concise, evidence-based Impact Connection / IDP responses from time-bounded GitHub and Slack activity. |
<!-- /generated:standalone -->

<!-- generated:counts (crew-lint.py --write-readme) -->
4 crew agents (orchestrators and workers), 11 personas, 13 skills, 20 `crew` commands and 24 installed commands.
<!-- /generated:counts -->

### Dashboard (optional)

A read-only terminal dashboard of tasks, running workers and locks, and the report; `t`, `w` and
`p` switch views, `r` refreshes, `g` reads `landed` from GitHub. It needs Textual, pinned in
`tui/requirements.txt` and never installed: from the repository root, run
`uv run --no-project --with-requirements tui/requirements.txt python3 tui/crew_tui.py`.
`python3 tui/crew_tui.py --once` prints the same views without Textual, and `crew ls --watch` is
the view with no dependency at all.

## What install changes

`install.sh` writes outside this repository. Knowing this before running it matters more than any
feature list.

| Path | What lands there |
|---|---|
| `~/.cursor/rules/`, `~/.cursor/agents/`, `~/.cursor/skills/` | Symlinks into this repository; `~/.cursor/hooks.json` is merged, not replaced |
| `~/.claude/CLAUDE.md`, `~/.claude/agents/`, `~/.claude/skills/`, `~/.claude/hooks/` | Symlinks and a managed block, plus hook registrations and permission rules merged into `~/.claude/settings.json` (backed up first) |
| `~/.codex/AGENTS.md` | A managed instruction block, the same content as the Claude Code one |
| `~/.agent/bin/` | One symlink per command in `.agent/tools/tools.json` |
| `~/.agent/install-manifest.json` | What install added to your settings files, so uninstall removes exactly that |
| `~/.agent/memory/`, `~/.agent/tasks/`, `~/.agent/journal/` | Your data: memory units, task state, journal. Created once, never overwritten |

No file is copied: the links point into your clone, so `git pull` updates everything. Run
`bash install.sh` again after a pull so new commands are linked and removed ones unlinked.

**It registers hooks that can block your commands**: a destructive-git guard, a secret-scanning
commit guard, a write-boundary check, a shell-expansion guard, and a worker-tree guard.
[Hooks](docs/hooks.md) describes each one and its off switch (`EL_CAPITAN_GUARDS=off` for all of
them); each is one small file you can read first.

**To reverse an install**, run `bash ~/el-capitan/install.sh --uninstall` (add `--dry-run` to print
each step and change nothing; `install.sh --dry-run` does the same for an install). It removes the
managed blocks, the hook registrations and permission rules the manifest records (an entry you had
before install stays), then the links into the checkout and the directories install created. For an
install from before the manifest, the oldest settings backup decides what was yours; with no backup
it lists the entries to review by hand. It exits 1 and names each link it left. Your `~/.agent` data
and the settings backups stay; delete them yourself if you want them gone.

`crew doctor` checks an install on one screen, and `crew gc` prunes old task state.

## Platform and requirements

| Requirement | Version |
|---|---|
| Platform | macOS and Linux, both tested in CI (Python 3.9 and 3.12); Windows is not supported |
| Cursor or Claude Code | The current release of either |
| Python | 3.9 or newer |
| Git, [`gh`](https://cli.github.com) (signed in), `jq` | Any recent version |
| [`shfmt`](https://github.com/mvdan/sh) | Optional: a real bash parser for the guards |
| [`uv`](https://docs.astral.sh/uv/) | Optional: runs the pinned test and lint tools when you work on el-capitan itself |

## Moving to a new machine

On the old machine, export your memory units (task state stays local):

```bash
~/.agent/bin/crew-mem.py export ~/el-capitan-memory.tar.gz
```

On the new one, install, then import:

```bash
git clone https://github.com/crespocarlos/el-capitan.git ~/el-capitan
bash ~/el-capitan/install.sh
~/.agent/bin/crew-mem.py import ~/el-capitan-memory.tar.gz
```

The import adds every unit and rebuilds the index; it never overwrites a unit already there.
[Memory](docs/memory.md) has the details.

Two things the export does not carry. Your personal preferences live in your clone
(`rules/personal.mdc`): push them to a fork and clone that, or copy the file. Your add-ons are the
regular files under `~/.cursor/agents` and `~/.cursor/skills`; list them with
`find ~/.cursor/agents ~/.cursor/skills -maxdepth 2 -name '*.md' ! -type l` and copy them too.

## Versions

`VERSION` holds the current version and [CHANGELOG.md](CHANGELOG.md) what changed in each release.
Both are written by [release-please](https://github.com/googleapis/release-please) from the
conventional commits merged to `main`; it opens a release pull request, and merging it tags the
release. The project is pre-1.0: the command surface is stable, the internal module layout is not.

## Documentation

- [Architecture](docs/architecture.md): the pipeline, the crew, file and state layout, the context
  budget, configuration, and extending el-capitan
- [Hooks](docs/hooks.md): every hook, the guard contract, and the off switches
- [Memory](docs/memory.md): how memory is written, recalled, and moved between machines
- [Glossary](docs/glossary.md): spec, gate, persona, hunk, and the rest
- [Contributing](CONTRIBUTING.md), [Security](SECURITY.md), [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE)
