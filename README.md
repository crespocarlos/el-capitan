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
| `crew open pr` | Write the PR description, then after approval ship the task (commit, push, draft PR, DONE) with crew-task.py ship. |
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
| `crew ls` [--all] [--repo R] [--status S] | Task table for the current repo, or the `ls.repo` scope of `~/.agent/config.json` (`--repo all` for every one, `--repo here` for the current one); IMPLEMENTING tasks idle for 14 days fold into one stale line; `--json` prints one object whose `items` add each task's issue, PRs, progress and activity. |
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

A terminal dashboard of tasks, running workers and locks, and the report. Each task shows
its GitHub issue and PRs (terminal links), its progress (checked over total criteria) and its activity
(`running <stage>`, `stuck <stage>` for a stage open past 6 hours, or days idle such as `idle 3d`). TOKENS is
what the task's agents used: **new** tokens (input, output and cache writes, summed over every call), such as `259k`,
or `~259k` when only the orchestrator's reported figure exists; a line under the table totals new tokens and cache
reads over the tasks shown. While an agent runs, ACTIVITY adds what it has used so far (`running review · 92k`),
read from its transcript under `~/.claude` or `$CLAUDE_CONFIG_DIR`. A task is DONE once a PR
for it is open: `crew open pr` records the PR and marks it, and the merge comes later. `t`, `w` and
`p` switch views, `r` refreshes, `g` reads `landed` from GitHub, and `o` and `O` open the selected
task's issue and PR in the browser. `s` lists the `crew-task.py` moves the selected task's state allows:
approve (`mark-approved`), start (`mark-implementing`), mark done (`mark-done` with the newest recorded
PR), close as done (`mark-done --force` with a note, by default `none (committed to main)` for
IMPLEMENTING and `closed: stale` otherwise, on a DRAFTING, APPROVED, IMPLEMENTING or ON-HOLD task with no
PR to mark done with; never on ABANDONED; LANDED then reads `closed`) and `blocked`
with a reason. Each move shows the exact command in a confirm dialog, which is your approval for a gate,
then runs it and shows its output and exit code; a refusal shows the reason. The dashboard never writes a
file itself and never calls a model. It needs Textual, pinned in
`tui/requirements.txt` and never installed: from the repository root, run
`uv run --no-project --with-requirements tui/requirements.txt python3 tui/crew_tui.py`.
`python3 tui/crew_tui.py --once` prints the same views without Textual, and `crew ls --watch` is
the view with no dependency at all.

The TUI, `crew ls` and `crew report` list the same repositories. Without `--repo` they read the
`ls.repo` scope of `~/.agent/config.json`: `here` (the default: the repository around the current
directory, or every one outside a repository), `all`, or one `owner/name`. `--repo` overrides it for
one run, and `--repo here` forces the current repository. For example, `{"ls": {"repo": "all"}}`
lists every repository from anywhere. An invalid value stops the command with exit 2 and names the file.

## What install changes

`install.sh` writes outside this repository. Knowing this before running it matters more than any
feature list.

| Path | What lands there |
|---|---|
| `~/.cursor/rules/`, `~/.cursor/agents/`, `~/.cursor/skills/` | Symlinks into this repository, except the read-only agents, written as files rendered with your `mcp` servers; `~/.cursor/hooks.json` is merged, not replaced |
| `~/.claude/CLAUDE.md`, `~/.claude/agents/`, `~/.claude/skills/`, `~/.claude/hooks/` | Symlinks and a managed block, plus hook registrations and permission rules merged into `~/.claude/settings.json` (backed up first) |
| Every other Claude config dir: `$CLAUDE_CONFIG_DIR`, each `--claude-config-dir DIR` | The same settings merge (the hooks stay in `~/.claude/hooks`); no CLAUDE.md block, because Claude Code reads the user CLAUDE.md from `~/.claude` whatever the config dir. `agents` and `skills` are linked into `~/.cursor`, or, when one is a real directory, each crew entry is linked inside it beside your own; your own links and files there are kept and named, never replaced. The dirs are recorded, so a later install, uninstall and `crew doctor` cover them; a recorded dir you deleted is dropped, not recreated. The hooks come only from this merge (the checkout's own `.claude/settings.json` registers none), so a config dir created after your last install has no guards, even inside this checkout, until you re-run `install.sh` with it set |
| Each config dir's `settings.json`: the task directory | Your `~/.agent/tasks`, written as an absolute path, in `permissions.additionalDirectories`, and an `Edit(~/.agent/tasks/**)` allow rule (it covers Write and MultiEdit too), so crew agents, background builders included, write task files without a prompt, `SPEC.md` included. The `check-task-spec-owner.sh` guard still refuses another task's spec, any Edit, MultiEdit or Write that changes a spec's `## Status` value (use `crew-task.py mark-approved`, `mark-implementing` or `mark-done`), and writes to `.task-id`, `PROGRESS.md` and review evidence. Bash gets a tripwire, `guard/task-files.sh`: a redirect, `tee`, `dd`, `truncate`, `ln`, `rm`, an in-place edit (`sed`, `perl`, `ruby`, `awk`) or a Python snippet whose literal target is one of those files is refused, and so is any `cp`/`mv`/`rsync` into a task directory. The gates also stamp each status move in PROGRESS.md, and a `## Status` that differs from the stamped one shows as `TAMPERED` in `crew ls` and blocks every gate until you run `crew-task.py restore-status <TASK_DIR>`, or, in your own terminal, `--accept <note>` to keep the spec's value (`guard/owner-only.sh` refuses `--accept` from an agent). These catch accidental and literal writes and make a deliberate bypass visible; they are not a lock. An agent with a shell running as you can still forge local files (a path in a variable, `eval`, a script written now and run later), so the real gate is the harness's permission prompt on the gate commands plus your review of the PR ([docs/hooks.md](docs/hooks.md), "Status integrity"). The `SPEC.md` `ask` rules an earlier install added are removed on the next install; an `ask` rule you added yourself stays. Uninstall removes only the entries install added; your own directories stay |
| Each config dir's `settings.json`: `autoMemoryEnabled` | `false`, so crew memory is the one memory store; written only once that dir's Claude auto-memory entries are imported ([Memory](docs/memory.md#claude-code-auto-memory)). A value you set is kept |
| `~/.codex/AGENTS.md` | A managed instruction block, the same content as the Claude Code one |
| `~/.agent/bin/` | One symlink per command in `.agent/tools/tools.json` |
| `~/.agent/install-manifest.json` | What install added to your settings files and the read-only agents it rendered, so uninstall removes exactly that |
| `~/.agent/config.json` `mcp` | Your docs and code-search MCP server names (`{"docs": [...], "code_search": [...]}`); install adds them to the read-only agents' tool allowlists |
| `~/.agent/memory/`, `~/.agent/tasks/`, `~/.agent/journal/` | Your data: memory units, task state, journal. Created once, never overwritten |

Almost everything is a link into your clone, so `git pull` updates it. The read-only agents are the
exception: they are copies rendered with your `mcp` servers, and the next Claude Code session
re-renders any copy a pull or a config change made stale. Run `bash install.sh` again after a pull
so new commands, skill reference files and agent `references/` directories are linked and removed
ones unlinked; a prompt that moved text into a new reference finds it only after that run.

**It registers hooks that can block your commands**: a destructive-git guard, a secret-scanning
commit guard, a write-boundary check, a shell-expansion guard, and a worker-tree guard.
[Hooks](docs/hooks.md) describes each one and its off switch (`EL_CAPITAN_GUARDS=off` for all of
them); each is one small file you can read first. On macOS an idle session also shows a banner, at
most one per session every 10 minutes and none in a background job; `EL_CAPITAN_NOTIFY=off` turns it
off.

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
