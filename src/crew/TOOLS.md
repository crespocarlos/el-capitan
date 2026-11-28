# Agent tool catalog

Source lives under `src/crew/`, grouped by responsibility into subdirectories. `install.sh`
links every cataloged command (each `kind: command` entry in `tools.json`) into `~/.agent/bin/`,
which stays a flat, stable command surface, so installed paths do not change. A module is imported
and an asset is read, so neither is linked. `tools.json` is the machine-readable source of truth:
each entry records the `dir` it lives in and what it is. `crew-lint.py` validates it.

## Naming and layout

- **Executables are kebab-case** — `^crew-[a-z0-9-]+\.(py|sh)$`, for example `crew-ls.py`. A new
  command that does not follow it is a defect, not a style choice.
- **A Python module imported by another tool is snake_case** — `^[a-z0-9_]+\.py$`. Python cannot
  import a hyphenated module, so `task_status.py` stays snake_case while its siblings are CLIs. A
  module is an exception the catalog must declare: list it under `modules` in `tools.json` with
  `kind: module`, never leave it to be inferred from the file extension.
- **Every installable command takes the `crew-` prefix** — a command is what `~/.agent/bin` links,
  and every one of them is something a person or prompt invokes, whether or not a `crew` subcommand
  fronts it (`crew-ls.py` and `crew-review-hunks.py` alike). A module the user never types is not a
  command and is not installed; it stays snake_case and unprefixed (`task_status.py`).
- **`kind` is what tells them apart** — every `tools.json` entry declares `kind: command`, `module`,
  or `asset`. `install.sh` links `kind: command` and nothing else, and `crew-lint.py` fails a command
  whose basename lacks the prefix and a module that carries a command's basename.
- **The top level is by role:** `lib/` (generic helpers), `core/` (the domain logic, no entry points:
  `core/task`, `core/review`, `core/memory`, each verb a typed function), `harness/` (hook runtime and
  adapters), `tools/` (agent entry points), `scripts/` (owner entry points, with their own `maintenance`,
  `evals` and `nightshift` packages), `tui/`. An
  entry point's `audience` in `tools.json` fixes its directory; install links every audience but `dev`.
  `tools.json` and `TOOLS.md` stay at the root of `src/crew/`.
- **`lib/` is imported, never installed as a command.** `src/crew/lib/` holds the helpers every
  tool shares, each defined once (crew-lint `single-owner`); its map is below. Import paths:
  "Imports" in `src/crew/AGENTS.md`.
- **PROGRESS.md has one owner, `core/task/task_progress.py`.** It appends every entry as
  `[YYYY-MM-DDTHH:MM:SSZ] KIND: body` (TRANSITION, METRIC, BLOCKED, WORKTREE, PR, WARN) and reads them back;
  legacy local `[YYYY-MM-DD HH:MM:SS]` and `[YYYY-MM-DD HH:MM]` lines still parse. No other module names the file in code.
- **The installed surface is flat.** `install.sh` links each command into `~/.agent/bin/`, to its
  launcher in `~/.agent/venv/bin` (`[project.scripts]` in `pyproject.toml`). Catalog names are unique
  (`invalid-tool-catalog`).

| Directory | Commands | Modules (imported, not run) | Assets (read, not linked) | Purpose |
| --- | --- | --- | --- | --- |
| `tools/` | `crew-tool.py`, `crew-verify.py`, `crew-worktree.py`, `crew-mem.py`, `crew-pr-actions.py`, `crew-review-findings.py`, `crew-review-hunks.py` | `envelope.py` | — | The agent tools: `crew-tool.py`'s verbs (the typed core functions) in one envelope, and the agent commands no verb covers yet |
| `scripts/` | `crew-task.py`, `crew-doctor.py`, `crew-lint.py`, `crew-ls.py`, `crew-inbox.py`, `crew-evals-compare.py`, `crew-evals-inspect.py`, `crew-nightshift-e2e.py` | — | — | The owner's commands (`crew-task.py` also serves the TUI's moves and the hooks' `record-pr`, `report`, `usage`) |
| `scripts/nightshift/` | — | `client.py`, `location.py`, `checks.py`, `doctor.py`, `commands.py` | — | The nightshift HTTP client, the preflight probes, and the run operations |
| `scripts/evals/` | — | `evals_query.py`, `evals_report.py`, `evals_rows.py`, `evals_diagnose.py`, `evals_sources.py` | — | Inspect, compare, and diagnose evaluation runs |
| `scripts/maintenance/` | — | `lint_files.py`, `lint_catalog.py`, `lint_prompts.py`, `lint_references.py`, `lint_python.py`, `lint_writing.py`, `lint_style.py`, `lint_docs.py`, `lint_dead_code.py`, `doctor_checks.py`, `doctor_env.py` | — | Repository validation, the generated README blocks, the caller report, one module per lint family, and the install health check |
| `core/task/` | — | `api.py`, `task_status.py`, `task_state.py`, `task_record.py`, `task_progress.py`, `task_gates.py`, `task_resolve.py`, `task_report.py`, `ls_data.py`, `ls_report.py`, `task_gc.py`, `task_lock.py`, `task_artifacts.py`, `task_repo_facts.py`, `task_worktrees.py`, `task_worktree_cli.py`, `task_verify.py`, `task_verify_env.py`, `task_verify_report.py`, `task_verify_sources.py`, `task_guidance.py`, `task_guidance_kinds.py`, `task_prepare.py`, `task_prepare_spec.py` | `transitions.json`, `next-steps.json` | Guidance context, task state, review location, status migration, resolution, gates, worktrees, repository facts, next-step routing |
| `core/review/` | — | `review_vocabulary.py`, `review_models.py`, `review_parse.py`, `review_findings.py`, `review_coverage.py`, `review_layers.py`, `review_consolidate.py`, `review_render.py`, `review_report.py`, `review_records.py`, `review_workspace.py`, `review_pr_reads.py`, `review_pr_plan.py`, `review_cli.py`, `review_prepare.py`, `review_dispatch_stats.py`, `review_head.py`, `review_hunks.py`, `assemble_inputs.py`, `assemble_build.py` | `pr-review-threads.graphql` | Hunks and layer maps, findings, packages, PR threads, on-demand e2e runs |
| `core/memory/` | — | `memory_paths.py`, `memory_frontmatter.py`, `memory_store.py`, `memory_add.py`, `memory_search.py`, `memory_journal.py`, `memory_inbox.py`, `memory_maintenance.py`, `memory_transfer.py`, `memory_claude.py` | — | Durable units and immutable observations, and the import of Claude Code auto-memory |
| `harness/` | `crew-hook.py` | `adapters.py`, `claude_code.py`, `cursor.py`, `cursor_cli.py`, `codex.py`, `harness_install.py` | `claude-code.json`, `cursor.json`, `cursor-cli.json`, `codex.json` | The one hook entry point, a manifest and an adapter (`render`, `normalize`, `encode`) per harness, and the writer install and doctor share |
| `lib/` | — | `errors.py`, `files.py`, `git.py`, `git_config.py`, `gh_reads.py`, `reply_marker.py`, `claude_plugins.py`, `cli.py`, `clock.py`, `output.py`, `next_steps.py`, `markdown.py`, `runs.py` | — | Shared helpers: one atomic write, JSON and setting read, one git/gh runner and owner/repo parser, one UTC stamp, the CLI and output contracts, the runs ledger |
| `tui/` | — | `crew_tui.py`, `tui_app.py`, `tui_model.py`, `tui_views.py`, `tui_moves.py`, `tui_github.py`, `tui_widgets.py` | — | The dashboard (`uv run --group tui python -m crew.tui.crew_tui`), not installed |
| root | — | — | `tools.json`, `TOOLS.md` | The catalog |

The table is grouped by `kind`, which is what the manifest declares: a row's Commands column is
every `kind: command` entry in that directory, so `install.sh` links exactly those basenames and
nothing else.

`crew-mem.py`, `crew-review-findings.py`, `crew-ls.py`, `crew-tool.py`, `crew-evals-compare.py`,
and `crew-lint.py` are argparse entry points over their modules: each parses the command line and
dispatches, and holds no command logic. Modules import each other by their namespaced name in
dependency order (`memory_paths` → `memory_frontmatter` → `memory_store` → `memory_add`/`memory_search`/
`memory_journal`/`memory_inbox` → `memory_maintenance`, `memory_store` → `memory_transfer`/`memory_claude`; `review_vocabulary` → `review_models` →
`review_findings` → `review_render`/`review_layers` → `review_coverage` → `review_report`; `task_status`
→ `task_progress` → `task_state` → `task_resolve`/`task_gates`/`ls_data` → `task_report`; `evals_query` →
`evals_report` → `evals_diagnose`/`evals_sources`; `lint_files` → `lint_catalog`/`lint_prompts`/
`lint_references`/`lint_writing`/`lint_python`, `lint_writing` → `lint_style`, `lint_catalog` → `lint_docs`), so a module never imports back
into one that imports it. Import paths: "Imports" in `src/crew/AGENTS.md`. The entry points
re-export the names their public contract names, listed in each one's `__all__`, so the tests can
keep importing them from the command file rather than reaching into a private module.

**Roles import along these edges only** (crew-lint `package-direction`; a module's role is its top-level
directory under `src/crew/`, and `lib` imports nothing from crew). The entry points and the TUI reach the
domain through `core`; only the owner's scripts read the harness adapters (lint and doctor, in
`scripts/maintenance`), and neither `core` nor `harness` imports the other:

```package-edges
core -> lib
harness -> lib
tools -> core lib
scripts -> core harness lib
tui -> core lib
lib ->
```

**The module ceiling covers every package.** No module under `src/crew/` exceeds 400 lines,
wherever it lives: `crew-lint`'s `module-size` rule derives the capped set from the tree rather than
from a list, so a package added tomorrow is capped the moment its directory exists. There is no
per-package exception and no exception by filename.

**Claude config dirs.** `install.sh` merges the settings and links `agents` and `skills` into every
Claude config dir (`~/.claude`, `$CLAUDE_CONFIG_DIR`, each `--claude-config-dir`), but writes the
CLAUDE.md blocks into `~/.claude/CLAUDE.md` only. The docs (claude-directory.md) say "If you set
`CLAUDE_CONFIG_DIR`, every `~/.claude` path on this page lives under that directory instead", which
would include `CLAUDE.md`. Observed: the user CLAUDE.md is read from ~/.claude even with
CLAUDE_CONFIG_DIR set (2026-11-27): a `CLAUDE_CONFIG_DIR=~/.claude-work` session with no
`~/.claude-work/CLAUDE.md` (and no link) loaded `~/.claude/CLAUDE.md`. A block in the second dir could
therefore load every rule twice. `autoMemoryEnabled: false` is written by the settings merge
(`AUTO_MEMORY_OFF`) once a dir's Claude memory is imported, never carried in the template.

**Rendered files.** Every file a harness reads is what its adapter's `render()` returns
(`src/crew/harness/`), written and recorded (`rendered` in the manifest) by `harness_install apply`. An agent whose
frontmatter `tools:` line ends in the YAML comment `  # {{mcp_servers}}` is rendered as a regular file, the comment
replaced by one `, mcp__<server>__*` per server in `mcp.docs` and `mcp.code_search` of `~/.agent/config.json`
(removed when none is); every other agent is a link. Only the frontmatter line counts. The session-start rule
`agents-refresh.sh` (`harness_install refresh`) rewrites each recorded file that differs from its render, and
`crew doctor` names each one that differs (`harness_install diff`). Uninstall removes them all.

## Module maps

One line per module: what it owns. Entry points (`crew-*.py`) are listed in the table above.

### `task/`

- `task_status.py`: the `## Status` contract, the review location, the typed `## Tests` rule
- `task_state.py`: the SPEC record (its issue and PR list included), the status write, reconcile rules, the status migration
- `task_progress.py`: PROGRESS.md: append and read every entry (BLOCKED, METRIC, stage cost and PR lines included)
- `task_gates.py`: the transition gates: approve, implement, close out
- `task_usage.py`: a subagent run's usage, appended as `agent_end` to the task its `crew-task:` line names (Claude Code: its transcript's tokens; Cursor: `tokens=unknown` with duration, tool calls and messages), and `crew-task.py usage stop`: a Cursor `stop`'s raw counts as `cursor_stop`
- `task_cost.py`: usage per agent kind and harness, Cursor session tokens (each count's rise once), and the `crew ls --cost` lines
- `task_builder_report.py`: a builder's reply saved as its task's `REPORT.md` (a batch's part report; the `final` batch both), by the `capture-reply.sh` hook or `crew-task.py report save` (stdin); a report that fails `report-check` is saved with a `WARN` line in PROGRESS.md
- `task_live.py`: the TUI's tokens of agents still running: transcripts modified in the last 15 minutes whose first user line names the task, read on from a per-file cache
- `task_record_pr.py`: `crew-task.py record-pr`, the PR hook: the task of a `gh pr create` PR (from `gh pr view`), marked done, given the PR, or created minimal and DONE
- `task_ship.py`: `crew-tool.py task-ship TITLE BODY_FILE BASE REPO [--task-dir T [--phase]]`, run in the task's recorded worktree (or the current checkout) after the owner's go. Exit 2 before anything runs when the task is not IMPLEMENTING, the worktree is missing, on another branch or of another repository, `mark-done` would refuse it (with `--phase`, only a review that does not cover HEAD counts), or the approved base and target differ from its own resolution. Then: stage (never an ignored file; an untracked or staged file named like a secret or over 1 MB stops it), commit (after scanning the added lines with the credential hook's pattern, `.claude/hooks/lib/token-patterns.ere`), merge the freshly fetched base, re-run the spec's `## Tests` commands (10 min each, 20 in all, every `CLAUDE*` variable unset, the process group killed on exit; files they leave stop it), push (never forced), open or reuse this head's open draft PR (`task_prs.branch_urls`), then `mark-done`, or with `--phase` (one PR of a program) `append_pr` with the task left IMPLEMENTING; each finished step appends `SHIP: <branch> <step> <value>` to PROGRESS.md and a re-run on that branch resumes at the first missing step or the first whose re-check fails (the PR's must still be OPEN), so a later phase on a new branch starts fresh
- `task_ship_checks.py`: what `ship` refuses to commit: untracked or staged files named like a secret or over 1 MB, and added lines matching the credential hook's pattern
- `task_resolve.py`: task resolution: repo and branch to `.task-id`
- `task_report.py`: rendering task state for `crew-ls.py`, the ISSUE, PR, PROGRESS, ACTIVITY and TOKENS cells, the 120-column fit, and `reconcile`
- `ls_data.py`: what `crew ls`, `--report` and the TUI read: rows, the repo filter (`--repo`, else `ls.repo` of `~/.agent/config.json`: `here`, `all` or an `owner/name`) and the state filter, stale, the `landed` lines, landing bases, `--watch`
- `task_prs.py`: the branch PRs reconcile asks GitHub for: due tasks, a fork's parent, the 24-hour cache, the thread pool and its budget
- `ls_report.py`: `crew-ls.py --report`: opened and closed, verdicts, findings and fixed rate, the window's tokens, stage costs and durations, tool failures
- `task_gc.py`: `~/.agent/config.json` (`gc`, `doctor`, `ls`, and `mcp`: `{"docs": [...], "code_search": [...]}`, the MCP server names `crew-doctor.py` looks for, empty by default so el-capitan names no vendor server; defaults, validation, exit 2 on a bad value), the retention policy (with the hook logs under `~/.agent/state`, pruned line by line; `--only telemetry` selects those and the legacy telemetry), `crew-task.py gc`, the state sizes `crew-doctor.py` checks
- `task_lock.py`: the worker lock (written, read across the worktrees, removed), the worker-tree rule every lock write, implement move and ship runs, and BLOCKED lines
- `api.py`: the task verbs as typed functions (`crew-tool.py task-*`, `repo-facts`, `guidance`), each a dataclass or a `ToolError`
- `task_artifacts.py`: bounded task artifacts: each one's text, cut at its edge
- `task_repo_facts.py`: the repository record a prompt reads: root, branch, head, remotes, files
- `task_worktrees.py`: worktree reads: listing, `worktree check`, `worktree pref|record`
- `task_worktree_cli.py`: worktree writes and the `crew-worktree.py` subcommands: create, sync, prune, remove
- `task_verify.py`: the `crew-verify.py` run: gates, the mirror, `--background`/`--wait` (polls every second; `CREW_VERIFY_POLL_SECONDS` overrides it)
- `task_verify_env.py`: Node pin, pass cache, result file, partial verdict
- `task_verify_report.py`: `crew-verify.py report-check` of a builder's REPORT.md
- `task_verify_sources.py`: where gates come from: CI workflows, the gates block, prose checks
- `task_guidance.py`: repository guidance per path (`crew-tool.py guidance`), and memory recall in process
- `task_guidance_kinds.py`: guidance ranked per agent kind (reviewer lens, builder, explorer, resolver), sections naming the agent's paths first, under one cap per kind, with a note naming each section the cap dropped; the one place those defaults live
- `task_prepare.py`: `crew-tool.py task-prepare implement`, crew implement's setup before the builder in one call
- `task_prepare_spec.py`: `crew-tool.py task-prepare spec`, crew spec's setup before the explorer in one call

### `review/`

- `review_vocabulary.py`: the closed finding vocabularies and the persona-reply classifier
- `review_models.py`: the `Finding` record and the probe score rules
- `review_parse.py`: unified-diff parsing and the generated/oversized size policy
- `review_findings.py`: the finding gates, anchors outside the diff, `normalize` and `validate`
- `review_coverage.py`: persona selection and coverage, package rules, the persist gates
- `review_layers.py`: the layer map: validation, hunk references, per-layer reports
- `review_consolidate.py`: the `consolidate` subcommand: grouping and `candidates.json`
- `review_render.py`: rendered findings, generated sections, the degraded mark, `save-out` and provenance
- `review_capture.py`: `expect` (a persona's, the probe's or a spec subagent's dispatch nonce and marker line) and `capture`, the subagent-stop hook (Claude Code and Cursor) that saves the reply, and `save-out --from-transcript`
- `review_transcript.py`: which file holds a stopped subagent's transcript, and the content-free diagnostic line when none does
- `review_report.py`: `persist`: writing the report and gating it against the findings JSON
- `review_records.py`: deferred and dropped records, the cost METRIC, the outcome journal
- `review_workspace.py`: where a review writes, and the content manifest of what it read
- `review_pr_reads.py`: the read half of `crew-pr-actions.py`: running and printing PR, repo, issue and thread reads
- `review_pr_plan.py`: the write half: the `gh` mutation plan, `comments` and `check-map`
- `review_cli.py`: the `crew-review-findings.py` subcommand definitions
- `review_prepare.py`: `prepare`, a review's setup in one call for every mode
- `review_dispatch_stats.py`: `dispatch-bytes` (bytes, guidance and shared prefix per prepared dispatch prompt) and `cache-report` (one review run's cache counts per persona above the first persona's, and its wall time)
- `review_head.py`: a PR's changed files at its head SHA, one GraphQL call per 100 paths, under `head/files/`
- `review_hunks.py`: the hunk artifacts `crew-review-hunks.py` and `prepare` write
- `assemble_inputs.py`: what each reviewer package reads: config, personas, header, prior round
- `assemble_build.py`: building and writing the reviewer packages and their manifest record
- `review/nightshift/` (`client.py`, `location.py`, `checks.py`, `doctor.py`, `commands.py`) backs
  `crew-nightshift-e2e.py`

### `memory/`

- `memory_paths.py`: store locations, scopes, slugs, tokens, `MemoryStoreError`
- `memory_frontmatter.py`: the unit format: scalars, frontmatter parsing and rendering
- `memory_store.py`: the FTS5 index and committing a change (`mutate`)
- `memory_add.py`: unit writes: add, cite, supersede, archive (used by `consolidate`), list, show
- `memory_search.py`: retrieval: `search` and ranked `context`
- `memory_journal.py`: journal observations: import and single-entry add
- `memory_inbox.py`: intake: `.inbox` drafts
- `memory_maintenance.py`: init, consolidate (`crew-inbox.py` fronts `memory_inbox.py`)
- `memory_transfer.py`: `export` (regular unit files only, a new 0600 `.tar.gz`, owner names cleared)
  and `import` (every member checked before any write: layout, 256 KiB and count/total caps,
  frontmatter, type, status, scope against its path, id and case-folded name collisions; a stored
  unit that differs is kept; a failed write leaves nothing)

### `evals/`

- `evals_query.py`: Elasticsearch access: the HTTP call and the score and trace queries (read-only)
- `evals_rows.py`: the eval score row, normalized once at the JSON boundary
- `evals_report.py`: comparison rendering: rows, tables, the per-trace summary
- `evals_diagnose.py`: change attribution for `diagnose`: the sign test, pairing, the JSON bundle
- `evals_sources.py`: suite source discovery and changed-path classification for `diagnose`

### `lib/`

- `cli.py`: `fail` (a refusal on stderr, exit 2) and `EXIT_INVALID`; parsers are plain argparse
- `clock.py`: the UTC stamp and the parser that also reads legacy local stamps
- `files.py`: `atomic_write`, `read_json_object`, `agents_setting` (a repo's AGENTS.md setting)
- `git.py`: every git argv and the gh runner, `slug_from_url`, `repo_name_from_url`, the network reads
- `git_config.py`: the repository root, its git directory and `origin_url`, read from files without running git
- `claude_plugins.py`: Claude Code plugin installs, the MCP servers their manifests declare, `enabledPlugins`
- `gh_reads.py`: the gh argv of one PR, repo or issue read and its argparse verb
- `reply_marker.py`: the dispatch marker line and the `<name>.expect` nonce the capture hook checks it against
- `output.py`: bounded output: the size ceiling, row limit and truncation marker
- `next_steps.py`: the next-step table; it reads the asset `task/next-steps.json`
- `markdown.py`: fenced code blocks (`fenced_blocks`) and frontmatter (`frontmatter`, PyYAML), each read once

### `maintenance/`

- `lint_files.py`: the in-scope document set, shared path helpers, the rule registry (`RULES`)
- `lint_catalog.py`: `tools.json`: kinds, fields, resolution, basename naming
- `lint_prompts.py`: prompt frontmatter, tool grants, the always-on budget and size ceilings
- `lint_references.py`: reference integrity in documents and the `> Next:` handoff grammar
- `lint_python.py`: the repository Python rules (module size, single owner, package edges, git argv)
- `lint_writing.py`: removed command forms, docstrings, narration, pipeline prose rules
- `lint_style.py`: the writing standard for prompt files (emphasis, emoji, narration, shared
  passages, glossary, vendor scope, placeholders, the closing confirmation)
- `lint_docs.py`: the one generator of the README command table and counts (`--commands`, `crew
  help`; `--write-readme`), their staleness rules, and the release files
- `lint_dead_code.py`: the caller set for a catalog command (`--dead-code`)
- `doctor_checks.py`: the `crew-doctor.py` checks: links, hook registrations, managed blocks (`.claude/install_blocks.py`), auto-memory, tools,
  state sizes
- `doctor_mcp.py`: the rendered read-only agents (a copy in `~/.cursor/agents` that differs from what install renders now is a `FAIL`) and the
  docs and code-search MCP capabilities. Server names come only from `mcp` in `~/.agent/config.json`; with none, one `note` says how to add
  them, and with an invalid config one `note` says so; nothing is checked then. Claude Code: each existing config dir (the recorded ones and
  `$CLAUDE_CONFIG_DIR`), reading `$CLAUDE_CONFIG_DIR/.claude.json` for the dir the variable names and `~/.claude.json` for `~/.claude`
  otherwise: a project reaches the user `mcpServers` minus its `disabledMcpServers`, its own, and the cwd repo's `<repo>/.mcp.json` servers
  that are approved (`enabledMcpjsonServers` or `enableAllProjectMcpServers`, in the project entry or the dir's `settings.json`) and not in
  `disabledMcpjsonServers`. Cursor: `~/.cursor/mcp.json` and `<repo>/.cursor/mcp.json`. A missing capability is a `WARN`, never a `FAIL`;
  plugin and claude.ai connector servers are named as unchecked

## Contracts

- Executable Python tools expose `--help` and use exit code `2` for unavailable infrastructure or
  invalid invocation.
- **`--help` fits one screen.** Every cataloged command's `--help` is at most 40 lines: purpose, one
  line per flag, one example when the invocation is not obvious. Reference material lives in this
  document, which a model reads only when it needs the detail;
  `evals/tools/test_command_names.py` enforces the ceiling.
- **The output contract is data in `tools.json`.** Each command entry may carry `output`
  (`human`, `json`, `json-always`, `json-flag`, `json_static`, `source-only`), `bounded` with the
  `list_flags` it accepts, and a `json_smoke` invocation. The same test asserts every documented JSON
  mode parses and every bounded command advertises its flag, so a new flag cannot go undocumented and
  a documented flag cannot go missing. A command a `crew` verb routes to carries `routes`: each verb
  with the one-line summary the README command table and `crew help` show (`lint_docs.py`).

| Command | Output | Bound |
|---|---|---|
| `crew-tool.py` | the envelope as concise text, compact JSON with `--json`, one field bare with `--field` | `--limit`, `--max-chars` (per verb) |
| `crew-lint.py` | findings, or JSON with `--json`; `--commands` a Markdown table; `--dead-code` a table of caller counts, or JSON with `--json` | — |
| `crew-ls.py` | table, `--md`, or with `--json` one object whose `items` are the tasks; `--report` text or JSON | `--limit`, `--max-chars` |
| `crew-doctor.py` | one screen of `ok`, `note`, `WARN` and `FAIL` lines; exit 1 on a `FAIL` only | — |
| `crew-mem.py` | text; JSON for `search`, `context`, `list` with `--json` | `--limit`, `--max-chars` |
| `crew-review-findings.py` | text; JSON for `select`, `coverage`, `normalize` | `--max-chars` |
| `crew-review-hunks.py` | JSON summary | `--max-chars` |
| `crew-nightshift-e2e.py` | JSON always (needs a nightshift server) | `--limit`, `--max-chars` |
| `crew-evals-inspect.py` | JSON always (needs Elasticsearch) | `--limit`, `--max-chars` |
| `crew-evals-compare.py` | tables; JSON for `diagnose --json` | — |
| `crew-worktree.py` | the path, or JSON with `--json` | `--max-chars` |
| `crew-pr-actions.py` | a plan or the threads as JSON | — |
| `crew-tool.py` | the envelope: text, `--json`, or one field bare with `--field` | `--max-chars` (task-context) |
| `crew-task.py`, `crew-verify.py` | human text (`crew-verify.py` also writes a JSON result; `crew-task.py gc --json` lists the selected paths, each archived one with its tarball under `--apply`) | — |

- **Truncation is never silent.** `--max-chars` and `--limit` print one `[truncated: …]` marker naming
  what was dropped and which flag raises the bound; `--json` output becomes
  `{"items": [...], "total": N, "truncated": true, "hint": ...}` rather than an array that looks
  complete. The rule lives once, in `lib/output.py`; text keeps its head unless it is an append-only
  log or a report whose identity fields come last, which keeps its tail — the same rule
  `task-context` applies per artifact.
- `tools.json` also declares the external tool surface that lint resolves. `mcp_servers` maps an MCP
  server name to the tool names this repository uses on it; `native_tools` lists the harness tool ids
  an agent's `tools:` line may name. `crew-lint.py` reports `mcp-tool-unknown` for an
  `mcp__<server>__<tool>` reference that `mcp_servers` does not declare and `tool-id-unknown` for a
  native id outside `native_tools`; a project that adds either adds it here in the same change.
  `agents-inherit-tools` checks each agent's `tools:` line against its class in `lint_prompts.py`
  (`src/crew/AGENTS.md`, "Authoring agent and skill files").
- **`crew-tool.py` is the one agent surface** (`tools/`): each verb is a typed core function (`core/task/api.py`,
  `review_prepare`, `assemble_build`, `review_consolidate`, `review_report`, `review_pr_reads`, `memory_search`,
  `memory_add`) returning a dataclass or raising `lib/errors.ToolError` with an enumerated `code`; the command line
  is built from its signature, so an MCP server can register the same functions. Each answers `{v, ok, data |
  error:{code, step, message, hint}, warnings}` (`v` versions the records too); an argparse error is one line,
  exit 2. Reads: `task-context`, `task-list`, `repo-facts`, `pr-read`, `mem-recall`, `guidance`,
  `review-prepare`. Moves: `task-transition MOVE TASK_DIR` (approve, implement, done, block; no owner-only
  move), `task-log`, `task-prepare`, `task-lock`, `task-ship`, `review-dispatch`, `review-finish`,
  `review-record-outcome`, `mem-write`. The worker-tree rule lives in `task_lock.worker_tree` (lock write and
  remove, the implement move, ship); the credential scan in `task_ship`.
- `task-context` resolves `--task-dir`, else `CREW_TASK_DIR`, else this repo and branch: `state: ok`, or
  `state: none` with an empty `task_dir` (exit 0); git it cannot read is exit 2. `--artifacts` selects
  artifacts (`task_artifacts.py`), each bounded by `--max-chars`, keeping the tail for append-only logs and
  for reports whose identity fields are appended last. `TASK_DIR=$(crew-tool.py task-context --field
  task_dir)` is the shell form.
- `repo-facts` reads each field only when asked (`task_repo_facts.py`): one `git status --porcelain=v2
  --branch` for the tree fields, one `git remote -v` for the remotes; `default_branch` is the local symref
  unless `--network`. `diff_base`, `fork_point`, `diff_source`, `changed_files`, `diff_stat` and `diff`
  are the review diff: the fork point against the working tree, so committed and pending work both count.
- `crew-ls.py` only reads; every task-state write is a `task_gates.py` function, reached by an agent through
  `crew-tool.py` and by the owner (and the TUI) through `crew-task.py`. `crew-ls.py --status-file
  SPEC.md` is the single reader for the `## Status` contract, implemented in `task_status.py`; hooks
  and other tools import it and must not re-implement it. The listing and the reconcile report live
  in `task_report.py`, and every transition gate (approve, implement, done) lives in `task_gates.py`, so a refused transition's message
  is defined beside the check that produced it. Each gate first refuses a TAMPERED task: its Status is
  not the target of the newest status TRANSITION in PROGRESS.md (`task_state.tampered`; DRAFTING when
  there is none); `crew-task.py restore-status <TASK_DIR> [--accept <note>]` clears it.
- **DONE means a PR is open.** `mark-done --pr-url <GitHub PR URL>` appends the URL to the task's PR
  list (PROGRESS.md: the `PR opened:` of the DONE transition, then a `PR:` entry per later PR) and
  writes DONE; it refuses an unchecked criterion and a reviewed commit that is not an ancestor of HEAD
  (no review: skipped), but not a review verdict or a branch other than the task's. A refusal exits
  non-zero with the reason and still records the PR; `crew open pr` stops on it. On a DONE task it
  only appends the PR. The `record-pr.sh` hook runs the same gate the moment `gh pr create` prints a
  URL (`crew-task.py record-pr`, `task_record_pr.py`). The hook's match is, in order: a task of the
  PR's repositories whose PR list already holds the URL (an IMPLEMENTING one runs the gate, any
  other only reports "already has"); the head branch in `.task-id` `branch`; the single
  IMPLEMENTING task whose SPEC.md `## Branch:` names it and whose `branch` is still the drafting
  one (empty, its `spec_branch`, `main` or `master`; it is then updated). It runs the gate from the
  task's `.task-id` `worktree` (the absolute checkout `mark-implementing` records when its `origin`
  or `upstream` remote is the task's and it holds the recorded branch) when that checkout is still
  the task's repository and holds the branch, else from a worktree of that repository, else from
  one of the payload `cwd`'s. `mark-implementing` without `--branch` takes that checkout's branch
  and refuses with exit 2 on the default branch, on a branch another task records, in another
  repository or outside a checkout; on an IMPLEMENTING task already off the default branch it
  changes nothing. `crew-task.py reconcile` (`task_prs.py`) asks `gh pr list --head <branch>`,
  read-only, for each IMPLEMENTING task with no PR recorded and a branch off its repository's default
  branch, on 8 threads. When the task's repository is a fork and lists no PR, it asks the parent too
  and keeps the PRs whose head repository belongs to the fork's owner (`gh pr list --head` takes no
  `owner:branch`). Each answer, and each repository's default branch and parent (one `gh repo view`), is cached for 24 hours in
  `~/.agent/.pr-lookup.json`, so a task is asked at most once a day. `--pr-budget SECONDS` bounds
  the whole search: the session-start hook passes 3, a task with no answer by then (or a failed read,
  offline) stays unchecked and is counted in one `N task(s) not checked for a PR yet` line, and a
  run by hand has no budget. A lookup that raises prints `warning: PR lookup for <task>: …` and
  stays unchecked. With `--apply` it records the PRs and the cache. It lists the tasks ready to mark
  done (the reviewed commit checked against the task's branch tip, not the cwd's HEAD), and a task
  whose PR is open but which fails that rule under `PR open, not closable` with the reason; `ready to
  open PR` excludes a task with a PR. It never writes DONE. `crew ls --json` prints one object,
  `{"items": [...], "returned", "total", "truncated", "what"}` plus a `hint` when bounded, whatever the
  flags; each item adds `issue`, `prs`,
  `progress` and `activity` (`running <stage>`, `stuck <stage>` past 6 hours, or `idle 3d` from the
  last PROGRESS entry; not the 14-day `stale`) from `task_report.task_cells`, the same cells the TUI shows,
  and `tokens`: `{"new": int|null, "cache_read": int|null, "approximate": bool}` (`task_usage_totals`).
- **The status token is canonical and normalized on read.** `DRAFTING`, `APPROVED`, `IMPLEMENTING`,
  `ON-HOLD`, `DONE` are the five states; `ABANDONED` is a user-only side state the store may hold.
  `task_status.head` uppercases and strips trailing punctuation, so `done`, `Done`, and `DONE.` are
  one token, and `task_status.token` rejects anything outside that set with a message naming it.
  A writer must emit the canonical spelling: lowercase is a legacy value, never a second state.
  `crew-task.py normalize-status [--apply]` previews and applies the one-shot rewrite of every stored
  legacy token across `--tasks-dir`, reporting each file and exiting 0 when a second run finds
  nothing left to change.
- **A task's review may live outside the task directory.** `task_status.py` resolves it: the task's
  own `REVIEW.md` when present, otherwise the directory `review_dir` in the task's `run.json` names.
  Both `run.json` writers record it — `review_workspace.claim` when the review directory is created,
  and `persist` on every write — because a PR-mode review persists to a temp directory by design and
  would otherwise leave the close-out gate with nothing readable. The gate reads the `Reviewed at:`
  commit from that one file, and `mark-done` prints which file it read (`done:` on stdout, `note:`
  on stderr) so a refusal is auditable.
- `crew-review-findings.py` records three fields on a finding: `kind` (what sort of defect: its values
  are `KINDS` in the tool, `security`, `correctness`, `reliability`, `documentation`, `testing`,
  `other`), `confidence` (the reviewer's own belief it is real, an integer 1-5: `5 confirmed`,
  `4 strong`, `3 likely`, `2 uncertain`, `1 suspicion`), and `validation` (one sentence on what a
  `verified: true` check read and concluded). All are required on a finding that reaches a gate:
  `kind` by `require_kind` and `confidence` by `require_confidence`, because measured over 84 recorded
  reviews 713 of 719 findings had no `kind` and every one predates the score; `validation` wherever
  `verified` is true. A value outside 1-5 is rejected by the parser, which names the range. A
  `blocking` or `attention` finding scored below 3 is rejected with a redirect to `needs more info`:
  it is a request the reviewer does not believe, and the doubt belongs in a question. A score may rise
  only by resolving the unknown through a read: the raised record carries `confidence_from` (the old
  value) and a `validation` sentence naming what settled it, and a raise without that sentence is
  rejected, as is a `confidence_from` equal to the score, which records nothing. A score may fall on
  one record only: `probe: refuted` (a value outside `PROBE_OUTCOMES`, `confirmed`, `refuted`, or
  `inconclusive`, is refused at parse with the set named) with the same `confidence_from` pair and a
  `validation` sentence quoting the command and the observed output. A downward move without a
  refuting probe is refused, and a refuted `blocking` or `attention` is still held to the floor, so it
  drops or relabels to `needs more info` rather than persisting as a request scored 2. The score is the
  reviewer's belief, never a severity, and is never summed into a review-level number.
  `normalize` and `persist` apply those gates by default; `--lenient` is the escape and `--strict`
  is a no-op alias kept one cycle so a script written against the old default still runs.
  A fourth field, `excerpt`, is required on a `blocking` or `attention` finding whose evidence uses
  the PR-head form `path:line@sha`: the 2-3 lines actually read, stored on the record. Without it the
  record cannot be re-read once the session that held network access is gone; re-checking four such
  findings cost five `gh api` reads and three file reads. A working-tree finding needs none.
- `crew-review-findings.py comments --review-dir <dir> [--findings <f>] [--head <sha>]` writes
  `comments.md`, one paste-ready body per anchored finding, from the `comment` field each record
  carries. It exits 1 naming every finding still missing a body, so a partial file never reads as the
  whole set. `persist --mode pr` writes the same file itself and reports its path, warning rather than
  failing when a body is missing, because the report is valid without it. Nothing in either path
  calls `gh`: posting is external state the user asks for separately. `persist` also records
  `dropped` findings in `DROPPED.md` beside the deferred ones, because a finding cut for the nit
  budget was otherwise invisible to the reviewer who raised it.
- `crew-review-findings.py check-map <reply> [--output layers.json]` parses a `reviewer-layers` reply
  before anything packages it: exactly one fenced `json` block, valid JSON, a `layers` array. A stray
  comma inside the fence is otherwise reported by the coverage gate only after every persona has run,
  or hidden entirely when the block is hand-repaired before writing.
- `crew-tool.py review-record-outcome` appends one JSONL record per decision `crew review address`
  makes; `outcomes --review-dir <dir> --acted <id> …` reads them back and exits 1 naming any acted
  finding with no record, which is what fails a summary that skipped one. `outcome --confidence N
  --confidence-from M --validation "<the read>"` records the score a decision was made under when it
  raised one; the pair is required together and a rise is refused without the sentence naming the read
  that settled it, while an unchanged pair is refused as not a raise, so the journal's authoritative
  score carries the same halves a persisted finding does. A lower score needs `--probe refuted` too,
  for the same reason `review_models`' probe rules do, and the record then carries the outcome.
  `outcomes` reads a record only for the review it names. Two journal shapes exist
  (`<review>/outcomes.jsonl` and `<task>/review/outcomes.jsonl`) because the path follows the
  directory the caller named, so both are read; a relative `review_dir` resolves against its own
  journal.
- `crew-review-findings.py persist --files` records the reviewed paths and gates evidence against them;
  it deliberately does not compare that list with the diff. `persist` runs in three modes with no
  single base ref, so inferring one would be wrong more often than right. Tree identity is carried by
  `--head` instead: the done move (`task_gates.mark_done`) refuses unless the reviewed commit is an ancestor of HEAD. In PR
  mode `--head` is the GitHub head SHA, which the local checkout never fetches, so `persist` records
  it without a local existence check and requires it explicitly. A PR review is never a valid
  `mark-done` ancestor and `persist` rejects PR artifacts under a task directory.
- `crew-review-findings.py spec-context --persona <name> SPEC.md` prints the spec one persona's package
  carries (rule: "Spec in every code-mode package" in `context-tiers.md`).
  `check-packages --review-dir <task>/review/<ts> --personas <names>` rejects written `.in.md`
  packages that break that rule, embed filename-generated hunks, or (spec and idea modes, composed by hand)
  lack the second contract part's `## Finding things in the codebase`, and reports any check it skipped
  for a missing `SPEC.md` or `hunks.json`; `persist` runs it only for a directory holding
  a `package.diff`. When the assembler stamped the run (`manifest.json` `personas.questions_rule`), it also
  refuses a package whose last `## Questions for this lens` lacks 2 to 5 unindented list items; an unstamped
  directory passes with a `skipped.questions` note, and `persist` never runs that check.
- `crew-task.py mark-done --force` is a deliberate, user-invoked escape hatch that skips every
  evidence check, including review ancestry, and accepts a free-text note (`none (committed to
  main)`) in place of a PR URL, logged as `<from> → DONE (closed: <note>)` (stripped, a leading
  `closed:` in any case kept once; an empty note is refused). It closes DRAFTING, APPROVED,
  IMPLEMENTING and ON-HOLD, which also ends an open BLOCKED line; ABANDONED and an unset status are
  refused. DRAFTING and APPROVED take a note only: a PR URL there is refused until the spec is
  approved. It exists for a spec whose branch was intentionally rebased, whose work shipped without a
  PR, or that went stale (the TUI's close move); it is never used by a skill on its own initiative.
- `crew-lint.py --dead-code` reports catalog commands with no caller. A caller is a reference from a prompt
  (rules, agents, skills, the root `AGENTS.md`, the templates), a hook, `install.sh`, another tool's
  code or a CI workflow; a Python docstring or comment, the tool tree's `.md` docs and the catalog
  page are not callers, and tests are counted in their own column and never decide the verdict,
  because a test proves a command runs, not that the pipeline asks for it. `uncalled` — no reference
  at all — is the only automatic judgment and makes the command exit 1; `test-only` is listed for a
  person to decide. Pruning stays a human decision: this report deletes nothing.
- `crew-pr-actions.py` is the only tool that mutates GitHub. `--execute` is the single mutation
  switch: `reply` and `resolve` without it print a plan and exit 0 without invoking `gh`, and
  `--dry-run` names that behavior explicitly (the two are mutually exclusive). The plan's `command`
  field is the exact `gh` argv, so an operator can read or run it by hand. `fetch` takes `--dry-run`
  as well and defaults `--query` to the `pr-review-threads.graphql` asset, so the query text has one
  source. `fetch` prints a flat object — `pageInfo`, `threads`, and the counts `resolved`,
  `unresolvedCurrent`, `unresolvedOutdated` — rather than gh's raw GraphQL envelope, because every
  caller otherwise had to know `data.repository.pullRequest.reviewThreads` and a wrong guess read as
  `Cannot iterate over null`. Each entry in `threads` is the GraphQL node unchanged. The counts cover
  everything fetched, and `--cursor` merges later pages into the same set and recounts them. A failed
  fetch exits nonzero with gh's message and prints no JSON, so `threads: []` always means the PR has
  no review threads.
- **The reads have a verb; the writes stay literal.** `crew-tool.py pr-read view|diff|repo|issue`
  answers the GitHub questions a prompt used to ask with `gh pr view`, `gh pr diff`, `gh repo view`, and
  `gh issue view` plus a `--jq` per call: `--fields a,b` returns those fields in the order asked (`--field
  record` prints them as one JSON object for `jq`), and `diff` passes the patch through unchanged. A field
  gh did not return is null, so a caller can test it, while a failed call is the `gh` error carrying gh's
  own stderr — the same rule `repo-facts` follows for git facts.
  Mutations stay literal `gh` in the prompts: `gh pr create`, `gh pr comment`, `gh pr checkout`,
  `gh issue create`, `gh search`. A wrapper would hide the exact argv from the deny rules and
  the shell guard, which decide on the command text the caller wrote, so wrapping one turns a denial
  into a silent allow.
- **A stage's setup is one call.** `crew-tool.py review-prepare MODE [--task-dir T] [--root R]
  [--base REF] [--pr N --repo O/R] [--paths …] [--query Q] [--contract] [--compat]` writes the review
  directory, `diff.patch` (self: the fork point, or `merge-base(REF, HEAD)` with `--base` for a stacked
  branch, against the working tree; with no remote the base is `HEAD~1`, as for `repo-facts`.
  Untracked files are included through `git diff --no-index`, so the index is never touched, except
  secret-shaped names (`.env*`, `*.pem`, `*.key`, `id_rsa*`, `*.p12`, `credentials*`) and files over
  256 KiB, which the summary lists with the `git add -N` hint; changes: the staged diff; PR: `gh pr
  diff`, the head re-read after it, exit 2 when it moved), `paths.txt`, the hunk files, `manifest.json`
  and the prior round (self, changes), `head/` (PR), `agent-context.json`, `mem.md`, and
  `assemble.json` (`schema_version` 1) with `selected`, the size gate and `pending`: the keys the
  orchestrator writes (`questions`, and `size_gate` for a spine-sized diff); spec and idea runs stamp the
  questions rule in `manifest.json` instead. `review-dispatch` refuses while a `pending` key is
  unwritten (a persona with no question, an empty size gate), or, in an `assemble.json` prepared before
  `pending`, a `TODO(prepare)` entry is left. PR mode ignores `--task-dir`, and reads guidance only from a
  checkout whose repository name equals the PR's: the owner is not compared, deliberately, so a fork's
  checkout counts. `crew-tool.py task-prepare implement --task-dir T [--where worktree|here] [--branch B]` and
  `task-prepare spec --slug S [--bug] [--paths …]` do the same for crew implement (the batch plan first,
  then where the worker runs, the branch or worktree, `mark-implementing`, the stage metrics,
  `BASELINE.diff`, memory, `dispatch/builder*.md`, batched over 8 open tasks, never inside an atomic
  group; no lock, which the orchestrator writes at dispatch, after the bootstrap) and crew spec (the
  task directory, `.task-id`, the template, `SPEC_RUN` and the explorer prompt with its marker). Each
  prints its directory, then one summary line; a failure prints `<command>: <step>: <reason>` on
  stderr, exit 1 for a state the user decides (nothing to review, the worktree question, a dirty tree,
  a `--branch` other than the checked-out feature branch, an unreadable atomic line, an unapproved
  spec, no `origin`), exit 2 otherwise.
- **PR-head files come from one GraphQL query, not the tarball.** `prepare --mode pr` and
  `crew-pr-actions.py head --pr N --repo O/R --out DIR` ask `repository.object(expression:
  "<sha>:<path>")` for every changed path in one `gh api graphql` call (100 paths per call), the
  expressions passed as variables, against the head repository (a fork's own); the paths come from
  `gh pr diff` in both. Each text blob is written to `head/files/<path>`, apart from the index, so a
  PR's own root `index.json` cannot overwrite it; `head/index.json` records the SHA and each path's status: `ok`, `absent`
  (deleted at the head), `binary`, `oversized` (over 256 KiB, not written) or `truncated`, the last two
  with the one `gh api …/contents/<path>?ref=<sha>` read that fetches the file by hand. The tarball was
  rejected: it downloads the whole repository at the head for a diff that touches a few files, and
  unpacking an archive from the network is a path-traversal surface; the query reads only the changed
  paths, and a path with `..` or a leading `/` is refused before anything is written.
- `crew-review-hunks.py <diff> --out <dir>` writes `hunks.json`, `hunks.md`, `hunks.index.md`, and
  `package.diff` (the diff persona packages embed, generated files' hunks collapsed to one note),
  numbering every hunk `h1`, `h2`, … in diff order, including one synthetic hunk for a file with no
  textual change (binary, rename-only, mode change). It owns the ids: the persona Reading map and
  `crew-review-findings.py coverage` share them. `hunks.md` carries index plus bodies for the
  layer-mapping pass; `hunks.index.md` is the index alone, for a persona package that already holds
  the diff. Self-contained by design — hunk parsing is project-agnostic, so it must not
  depend on another checkout. Its ids, statuses, and lines match nightshift-pr-helper's
  `parseDiff`; that parity is what lets a crew review and a nightshift review of one PR cite the
  same `h1`.
- `crew-tool.py review-dispatch <review-dir>` composes one `<persona>.in.md` package per
  reviewer from files the run already wrote, in one order: the shared head (contract, lookups, mode, hunk
  reference, memory), then `package.diff` in full, then the per-persona tail (size gate, spec, reading
  map, guidance narrowed for that lens, prior-round block, consumer and prompt extras). The head and
  the whole diff are byte-identical across the run's packages, so a harness that caches a prompt
  prefix pays for them once instead of once per persona; the layout and its test are pinned in
  `.cursor/agents/crew-reviewer/references/context-tiers.md`. Per-run judgement (mode text,
  consumer excerpts, prompt files, size-gate line) comes from `assemble.json` in the review directory,
  so the shared parts cannot drift between personas. Consumer excerpts and prompt files are read from
  the git index, not the working tree, and `mode_kind: "pr"` refuses both because a PR review may not
  read the local checkout at all. The persona list is derived from `crew-review-findings.py`, and a persona
  with no `PRIMARY_KINDS` entry stops the run instead of shipping without a package.
- **Assembly decisions.** `review-dispatch` skips a persona that cannot apply (today Prompt
  Quality, when no changed path is a prompt, agent, skill, rule or a prompt embedded in code such as
  `**/prompts/*.md`, and no `prompt_files` were named) and records the skip, with its reason, in
  `manifest.json` under `personas` (merged, so `prior-review` keeps writing the keys it reads); it also
  prints a per-persona size report. `"slice": true` in `assemble.json` (needs `layers.json`) narrows only
  product-flow and code-quality to their primary layers plus a caller and callee closure, and refuses to
  slice when a hunk would reach no package; adversarial and architecture always get the whole diff.
  `--expand` is not built: the size report is the evidence for whether it would pay. `assemble.json`
  keys (all optional; a missing key means no such section): `repo`, `mode` (falls back to the label
  vocabulary and return shape), `mode_kind` (`pr` refuses `consumers` and `prompt_files`, which read
  the local index), `size_gate`, `consumers` (`[path, start, end, label]`), `prompt_files`,
  `guidance_keep` (`{persona: [level-2 heading prefix]}`), `report` (its Unverified claims go to every
  persona), `slice`, `skip_personas` (`{persona: why}`), `selected`, and `questions` (`{persona:
  [question]}`, rendered last as `## Questions for this lens`; `check-packages` requires 2 to 5 per package).
- **Evidence trail.** `crew-review-findings.py save-out` stores a persona's raw reply from stdin and a
  `<persona>.provenance.json` (`harness`, `agent_id|null`, `model|null`, `time`, `sha256`); `persist`
  verifies the hash when the record exists and passes a review directory without one with
  `provenance: absent (legacy)` (tamper evidence applies to new reviews only). Fewer agents than lenses
  is a `Degraded: 1 agent, N lenses` review capped at `WARN`. In Claude Code and Cursor the `capture-reply.sh`
  hook calls the same writer: `expect` writes `<persona>.expect` (a nonce) and prints the
  `crew-review-out:` marker the dispatch prompt carries; `capture` saves the reply when they match, records the
  nonce, keeps `.expect`, moves an earlier reply to the same marker to `<persona>.prev.md`, and leaves
  `<persona>.unanswered` beside a reply that answers nothing. `consolidate --review-dir D` only GROUPS
  candidates (`raw-candidates.json`; identical file and overlapping `line`..`line_end`, never title
  similarity) into a draft `candidates.json` that `normalize` reads unchanged: every original keeps its
  label, the representative carries `group_severity`, the others get `disposition: merged`, and hunk ids
  are resolved from file:line. `consolidate --render` writes `report.md` from `consolidation.json`.
  `normalize --files ... --repo R --head H` accepts a tracked file at `H` outside the diff as a
  `non-hunk` anchor (untracked is rejected; `[blocking]` needs `line_read: true`).
- **Gates and cost.** `crew-verify.py` runs the repository's CI as its CI runs it, reading it from
  the BASE branch, by mirroring its `run:` steps. Passes are cached (`--no-cache` re-runs) by (tree
  hash, command, env, Node version); a failure is never replayed. The workflow is parsed by PyYAML, every scalar kept as written, and CI workflow `run:` steps are the source whenever the repo has CI, the
  `AGENTS.md` `gates` block is the fallback for a repo with none, the repo's optional `gates.json` (in its `.agent` directory) may add gates and
  never changes a CI one (a clash prints a warning naming the gate and both commands) and stands alone
  only when it is the only source. It pins Node from the first of `.nvmrc`, `.node-version`,
  `.tool-versions`, `package.json` `engines.node` (none: "no Node pin found, using PATH"), names CI it
  cannot read ("CI not readable here (buildkite)") and falls through, and with no runnable gate prints
  the nearest `AGENTS.md`'s prose checks as "repo-declared check, run this: ..." (never run) plus
  "NOT VERIFIED" (exit 3, or 2 with `--strict`). It writes `gates.json` (`schema_version: 1`). `crew-task.py worktree pref|record` resolves where the
  worker runs (here by default) and records the one-time answer. `crew ls --watch [--interval N]`
  redraws the table (data from `ls_data.py`). The `AGENTS.md` settings (`gates`, `landing_bases`,
  `worktree`, `verify`, `e2e`) are documented in `src/crew/AGENTS.md`. `crew-tool.py task-lock write|remove` owns
  `.crew-worker.lock` and `task-transition block` writes the `BLOCKED:` line `crew ls` shows. `crew-tool.py task-log --metric` accepts
  `stage_start stage=<implement|review>` and `stage_end stage=... tokens_reported=<n|unknown>` (tokens
  only as the harness reported them), prints the cost line, and `crew ls --cost` totals them ("One token
  measure" below); `crew ls
  --all` shows `landed: yes|no|unknown` for done tasks, or `closed` for one closed with a note and no PR.
- **Review yield** is defined over accepted `[blocking]` and `[attention]` findings only: the findings
  a review stood behind (disposition `patch` or `decide`) divided by its persona runs, never counting
  `[nit]`, `[concern]`, `[needs more info]`, deferred or dropped findings.
- `crew-nightshift-e2e.py` targets Kibana by design (its ports, config keys and paths are Kibana's)
  and is the only nightshift-coupled tool: it drives the local nightshift-pr-helper
  server over HTTP for e2e runs and cannot be generalized. `doctor` is read-only and never calls
  `/api/state`, which advances the queue and can start a run. It never uses the queue or
  `post-comment` endpoints, because queued runs post a PR comment by default. Exit 3 means the
  server is unreachable. The entry point holds argparse and exit codes only; the `review/nightshift/`
  package beside it holds the HTTP client (`client.py`), the checkout and machine probes
  (`location.py`), the preflight table (`checks.py`), its assembly (`doctor.py`), and the run
  operations (`commands.py`).
- `repo-facts` answers the facts a prompt used to ask git for: `root`, `branch`, `head`, `head_short`,
  `upstream`, `staged`, `changed` (edited in the tree), `staged_dirty` (staged, then edited again: what
  `crew commit`'s fast path checks, since a restaged file keeps its staged name), `untracked`, `dirty`,
  `remote`, `remote_url`, `repo` (owner/repo), `repo_name`, `origin_repo`, `default_branch`, and the diff
  fields. `--field NAME` prints one value bare (a list one item per line) and exits 1 when that fact is
  unavailable; `--root PATH` reads another checkout; `--remote` defaults to `upstream`, else `origin`.
- **Git is reached through `lib/git.py`, never through a hand-rolled call.** No Python module outside
  that file builds a `git` or `gh` argv, and no prompt runs git to learn the root, branch, remote, or
  diff base — it asks `crew-tool.py repo-facts`. A module imports the helper for
  its question; a local read (root, branch, HEAD, ancestry, status, index, blob) lives in `git.py`
  and uses git alone, while the remote questions (default branch, remote tip, fetch, compare), in the
  same module, try `gh` first because it carries the authentication, and fall back to git, raising
  `GitError` that names both failures.
  Prompt files keep raw git only for a mutation the user approved (`git add`, `git commit`) and for
  documentation that says what must never run.
- `crew-worktree.py` has four operations, and it is the command a prompt uses for every worktree
  question and mutation. With no operation it resolves `BRANCH`'s worktree, creating it when absent
  (`-b BRANCH BASE` creates the branch too). `--list` prints JSON: each worktree's `path`, `branch`,
  `main` (the checkout it ran in), `merged` (an ancestor of the default branch), and `gone` (its
  upstream tracking ref was deleted), plus `stale` naming the paths a cleanup may offer. `fetch`
  refreshes the remote and prunes deleted branches. `sync --branch NAME` fetches `NAME` and checks it
  out here, creating it from `origin/NAME` when it does not exist — what `crew implement` uses
  instead of assembling `git fetch` and `git checkout -b`. `--remove PATH [--branch NAME] [--force]`
  removes the worktree first and the branch only after that succeeded, so a refused worktree leaves
  its branch alive and a refused delete names the branch it kept; `--force` is `-D`. It is stateful,
  so its usage output is available with `--help`; do not use smoke tests that create worktrees.
- `crew-worktree.py` auto-prunes only worktrees whose remote branch is gone and that are clean. It
  deletes the local branch with `git branch -d` and keeps unmerged ones; merged branches with a live
  remote are left for `--remove`.
- The `src/crew/core/evals` package targets Kibana by design (`@kbn/evals-suite-*` suites found by
  their `kibana.jsonc`). The Elasticsearch tools are read-only. `crew-evals-inspect.py` and `crew-evals-compare.py` use `ES_URL`,
  plus `ES_API_KEY` or `ES_USER`/`ES_PASS`. `evals_query.py` owns that access for the compare tool
  (the HTTP call and the paged score/trace queries), `evals_rows.py` the row record built from one
  score document, `evals_report.py` the printed tables and the per-trace summary, `evals_diagnose.py`
  the sign test and the change-attribution bundle, and `evals_sources.py` the suite lookup and
  changed-path classification. `evals/compare_run.py` imports the compare tool and reads
  `common_prefix`, `sign_test_pvalue`, and `classify_paths` from it, which is why the entry point
  re-exports them.
- Dependencies are pinned in `pyproject.toml` and `uv.lock`; `docs/dependencies.md` gives each one's reason.

## PROGRESS.md and METRIC lines

- **PROGRESS.md** is a task's append-only event log. Its one gate input is the status integrity check:
  the newest `[gate]`-stamped transition, which only `crew-task.py` writes, must match SPEC.md's Status;
  otherwise SPEC.md plus git and gh decide. Skills may read it for resume context. Its format and
  owner are `task_progress.py` (above); `crew-tool.py task-log --step` writes a pipeline step only and
  refuses a status target or the stamp (exit 2). The integrity check (TAMPERED) catches any other write to it.
- **METRIC lines** are append-only audit records for offline analysis, never parsed for gates or
  transitions. Write one with `crew-tool.py task-log "$TASK_DIR" --metric <event> [key=value ...]`; it is
  stored as one JSON object (`schema_version`, `event`, the fields, counts as numbers) through
  `task_progress.append_metric`, and read back only through `task_progress.metric`, which also reads the
  `event key=value` lines tasks recorded before JSON.
- **`agent_end`** is written by the `capture-reply.sh` hook (`task_usage.py`), never by hand: one per
  subagent whose prompt carries `crew-task: <TASK_DIR>`, with `harness=claude-code|cursor`. A Cursor
  entry has `tokens=unknown` (its `subagentStop` reports none) and counts toward no token total;
  `task_cost.agent_kinds` lists it per kind with its tool calls and duration. In Claude Code `tokens` is the last call's
  context (its input + cache write + cache read + output), the figure the harness reports; `input`,
  `output`, `cache_read` and `cache_write` are each summed over the calls (each assistant message
  once). Summed `cache_read` counts the cached context once per call, so it never enters the
  headline. The named directory must sit under `~/.agent/tasks` and hold `SPEC.md`. Each entry carries
  `agent_id`, and only an agent's latest entry counts, so a resumed agent's stops are not added up.
  `started=` is the dispatch (the transcript's first timestamp; Cursor: the stop less `duration_ms`), and
  `first_input`, `first_cache_read`, `first_cache_write` are the first call's counts;
  `crew-review-findings.py cache-report` prints them per persona of one review run, each first cache
  read above the first persona's own, and the run's wall time.
  `task_progress.agent_ends` is the one attribution both views use: an entry belongs to the stage of
  the `stage_start` before it (else `other`). A transcript with no usage field records nothing.
- **One token measure.** `task_progress.task_usage_totals` is what `crew ls --cost`, `crew ls --json`,
  `crew report` and the TUI show: **new** tokens (`input + output + cache_write`) and **cache reads**,
  each summed over an agent's calls and over the task's agents (each `agent_id` once). Each run of a
  stage with no `agent_end` adds its `stage_end`'s `tokens_reported` as new, marked `~` (a final
  context, not a sum). `crew ls --cost` reads `new 106k, cache reads 401k; review: 2 personas, new 106k`;
  `crew report` labels its line `tokens (last 30 days, all tasks)` because its window includes DONE
  tasks the tasks view hides. At the window's edge an agent counts when its latest `agent_end` falls
  inside, with its whole run, so a resumed agent brings the usage from before the window with it. The
  TUI's TOKENS column and total line sum the rows on screen; running agents' tokens (`task_live.py`)
  appear only in ACTIVITY and the workers view. Cursor sessions (`cursor_stop`, `task_cost`) and
  agents per kind and harness are shown apart from this measure, labelled.

## Hooks

Every registration runs one entry point, `crew-hook.py <harness> <event>` (`harness/crew_hook.py`), so moving a
rule file never strands an installed registration. The harness's adapter normalises the payload into one event
(`event`, `harness`, `deny_rules`, `cwd`, `session`, `tool`, `input`, and the fields of a stop), each canonical
event it serves runs the rules `.claude/hooks/contract.json` names for it from `~/.agent/hooks` (copied there at
install with the registrations, and stamped with the event's `version`), and the adapter encodes the answer. The rules know no harness (crew-lint `harness-knowledge`); one
contract, in `.claude/hooks/lib/hook.sh`:

| Outcome | A rule prints | Claude Code and Codex get | Cursor gets |
| --- | --- | --- | --- |
| Deny | `{"deny": MESSAGE}` | exit `2`, the message on stderr | `permission: deny` JSON, exit `0` |
| No objection | nothing | exit `0`, nothing | `{}` (a `failClosed` registration reads silence as a crash) |
| Context | text | stdout, or `additionalContext` after a tool call | `additional_context` at session start |
| Go on | `{"followup": TEXT}` | `decision: block` | `followup_message` |

A Claude allow is never a `permissionDecision: "allow"` payload, which would skip interactive approval.
**Cannot judge is no objection.** A missing `awk`, a command the normaliser cannot read or an unreadable event exits
`0` after one stderr line. A rule the contract marks `fail: closed` (the guards) that is missing, fails or times out
denies, as do rules of another version than `crew-hook.py`; an open one is skipped with one line. An internal error
of `crew-hook.py` denies an event a closed rule serves and allows the rest. The credentials rule denies the commands
it scans when it cannot scan them.

| Rule | Event | Purpose |
| --- | --- | --- |
| `guard/shell.sh` | `pre_shell` | the shell guard: one process, its rules as functions (`docs/hooks.md`, Rules) |
| `check-task-spec-owner.sh` | `pre_write` | the file guard: a `SPEC.md` written over another task's; without deny rules, Status moves; record deletes |
| `mode-anchor.sh` | `prompt_submit` | the cached pipeline anchor line |
| `memory-context.sh`, `agents-refresh.sh`, `spec-status-reconcile.sh` | `session_start` | memory context, the rendered files refreshed, the status policy and anchor |
| `log-tool-use.sh` | `post_tool` | local telemetry |
| `notify-idle.sh` | `idle` | the idle notification |
| `memory-capture-prompt.sh`, `usage.sh` | `stop` | one memory review queued; a stop's raw token counts as `cursor_stop` on its task |
| `record-pr.sh` | `post_shell` | `crew-task.py record-pr`: the PR a `gh pr create` printed, recorded on its task (`task_record_pr.py`) |
| `capture-reply.sh` | `subagent_stop` | `crew-review-findings.py capture`: the reply its `crew-review-out:` marker and `.expect` nonce name (`review_capture.py`), a builder's report, the run's `agent_end` |

One guard per event, one function per rule, so a false positive or a crash is confined to the rule
that caused it. `lib/hook.sh` is sourced, never registered; it holds the command
normaliser every shell guard reads through and the off switches (`EL_CAPITAN_GUARDS=off`,
`EL_CAPITAN_GUARD_<RULE>=off`, documented in `docs/hooks.md`). The normaliser is `shfmt` (on PATH, else
the venv's, pinned by the `shfmt-py` wheel): `shfmt --to-json` parses the command and `lib/segments.jq`
turns the tree into segment records; a command shfmt cannot parse, or one that nests deeply (shfmt's JSON
grows with depth times size), is too complex to judge. `evals/tools/test_harness_parity.py` runs every case
through each adapter. `lib/anchor.sh`
holds the anchor line `spec-status-reconcile.sh` computes and `mode-anchor.sh` reprints.

The review-address gate is the user's answer in `crew-address-review` Step 3; no hook or permission
rule records it.

## Sandboxed network and `gh`

Every `gh` command needs `api.github.com`, which Cursor's sandbox allowlist does not include, while
`github.com`, `codeload.github.com`, and `*.githubusercontent.com` are included. In a Cursor-sandboxed
shell `gh` therefore fails with `Get "https://api.github.com/…": Forbidden` and exits 1, and `gh auth
status` reports `X Failed to log in … (keyring)` / `The token in keyring is invalid`. Both are the
network gap, not credentials: `git ls-remote` and `git fetch` work in the same shell, and the same
commands succeed with `required_permissions: ["full_network"]`.

Run any `gh` call that must reach GitHub with network elevation from the start, and do not suggest
`gh auth refresh` on the strength of that keyring message. The durable fix is per-workspace state —
add `api.github.com` to the allowlist in `~/.cursor/sandbox-policies/` — which no repository file can
set. `curl -s -o /dev/null -w "%{http_code}" https://api.github.com` returns `000` when blocked and a
real status when allowed, which distinguishes the two cases in one call.

This section is Cursor-specific. Claude Code does not sandbox the shell, so `gh` works there
unmodified; the harness difference is recorded below so neither guide gets applied where it does not
hold.

## Harness differences that change what an agent may assume

The two harnesses differ in ways that produce false conclusions if you generalize from one:

- **Network.** Cursor sandboxes the shell against an allowlist (see above). Claude Code does not, so
  `gh`, `curl`, and API reachability questions have different answers in each. Never diagnose a
  Claude Code network failure from Cursor's symptoms or the reverse.
- **Workspace trust.** Claude Code ignores every `permissions.allow` entry in `.claude/settings.json`
  until the workspace is trusted in that harness (`projects["<path>"].hasTrustDialogAccepted` in
  `~/.claude.json`). Untrusted, `gh`, `git`, and `python3` calls need per-command approval, and in a
  non-interactive `claude -p` run they are simply refused. Cursor has no equivalent gate.
- **Write boundary.** Cursor's `Write` tool refuses `/tmp` and other paths outside the workspace
  worktree; Claude Code writes wherever the OS allows (`install.sh --sandbox` limits Bash).
- **Shell aliases leak into command substitution.** This workstation aliases `ls` to
  `eza --icons --group-directories-first`, which renders a symlink as `path -> target`. `eza` is an
  alias, not a builtin, so `$(ls a b | head -1)` captures the whole arrow string and the next command
  opens a filename that does not exist (`wc: … -> …: No such file or directory`). Agent directories
  are symlinks into the repo, so this fires on the most ordinary read here. Use `command ls` whenever
  the output becomes a filename, or skip `ls` entirely: `printf '%s\n'` a known path, or read the file.
  Counting (`ls … | wc -l`) is safe, because a glob that expands to many paths still prints one per
  line; only filename capture breaks. A bare `ls` also lists every symlink target twice when two
  directories point at the same tree, so its output is not a file list even when it looks like one.

When a guide says "elevate the command" or "the write was blocked", the advice is scoped to the
harness that produces that failure.

## Adding or retiring a tool

1. Add or remove the executable in its `src/crew/<dir>/` subdirectory and its `tools.json` entry
   — with the matching `dir` and `kind` — in the same change. A `kind: command` entry must be
   `crew-`-prefixed and executable; a `kind: module` entry is snake_case, not executable, and never
   linked.
2. Give it `--help` at most 40 lines, or document a specific exception in `help`.
3. Assign one category and one owning skill, agent, or `repository`.
4. Declare its output contract in the same entry: `output` (`human`, `json`, `json-always`,
   `json-flag`, `json-static`), `bounded` with `list_flags` when it prints a collection, and a
   `json_smoke` invocation the test can run hermetically. Add the row to the contract table above.
5. Add a deterministic smoke command if the CLI is safe to invoke.
6. Run `uv run crew-lint.py`, the listed smoke command, and
   `bash evals/test.sh evals/tools/test_command_names.py`.

## Handoff trailers

A reply that hands work on ends with one line, `> Next: ` followed by the `crew <verb>` command to
run next — the last non-empty line of the file, named once, and resolvable in `crew-router.mdc`.
`crew-lint` enforces it (`lint_references.py`), so a stage with several outcomes quotes one trailer per
outcome in backticks instead of emitting an unquoted one.

The text of the persisted report's `> Next:` line is not chosen when the file is written: it comes
from `task/next-steps.json` through `lib/next_steps.py`, keyed `<workflow>.<stage>.<outcome>`: each
rule prints ``run `crew <verb>` to continue``, a person's action for a PR review, or `decide: …` when
the next move belongs to the user. A skill's own trailer is written prose, not generated: editing the
table changes the report, never a skill file. What `crew-lint` holds a trailer to is its
shape and its router row, not agreement with the table.
`evals/tools/test_next_steps.py` holds every command in the table to a `crew-router.mdc` row, so a
stage cannot hand off to something the router does not route.

## Compatibility policy

Command basenames are public because installation creates matching `~/.agent/bin/<name>` symlinks.
A rename is therefore a breaking change: apply it in one change — the new basename, every caller in
this repository, the catalog entry, and this document — because no alias cycle exists. `install.sh`
links exactly the catalog's `kind: command` entries and `prune_retired_tool_links` removes any
`~/.agent/bin` link whose target is in this tool tree but whose basename is no longer cataloged, so
the stale link goes on the next install.
