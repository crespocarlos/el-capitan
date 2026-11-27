# Agent tool catalog

Source lives under `.agent/tools/`, grouped by responsibility into subdirectories. `install.sh`
links every cataloged command (each `kind: command` entry in `tools.json`) into `~/.agent/bin/`,
which stays a flat, stable command surface, so installed paths do not change. A module is imported
and an asset is read, so neither is linked. `tools.json` is the machine-readable source of truth:
each entry records the `dir` it lives in and what it is. `crew-lint.py` validates it.

## Naming and layout

- **Executables are kebab-case** — `^crew-[a-z0-9-]+\.(py|sh)$`, for example `crew-ls.py` or
  `crew-default-branch.sh`. A new command that does not follow it is a defect, not a style choice.
  One exemption, declared rather than inferred: `task-env.sh` is sourced, so it cannot be renamed —
  `source` needs a real file at a fixed path.
- **A Python module imported by another tool is snake_case** — `^[a-z0-9_]+\.py$`. Python cannot
  import a hyphenated module, so `task_status.py` stays snake_case while its siblings are CLIs. A
  module is an exception the catalog must declare: list it under `modules` in `tools.json` with
  `kind: module`, never leave it to be inferred from the file extension.
- **A module name is namespaced to its tool** — `memory_store.py`, `review_findings.py`, never a
  bare `store.py` or `findings.py`. Generic names collided once a tool put its directory on
  `sys.path`, so a shared name is now a defect: prefix it with the package it belongs to.
- **Every installable command takes the `crew-` prefix** — a command is what `~/.agent/bin` links,
  and every one of them is something a person or prompt invokes, whether or not a `crew` subcommand
  fronts it (`crew-ls.py` and `crew-review-hunks.py` alike). A module the user never types is not a
  command and is not installed; it stays snake_case and unprefixed (`task_status.py`).
- **`kind` is what tells them apart** — every `tools.json` entry declares `kind: command`, `module`,
  or `asset`. `install.sh` links `kind: command` and nothing else, and `crew-lint.py` fails a command
  whose basename lacks the prefix and a module that carries a command's basename.
- **One subdirectory per responsibility** — `lib/`, `task/`, `review/`, `memory/`, `evals/`,
  `maintenance/`. `tools.json`, `TOOLS.md`, and `requirements.txt` stay at the root of
  `.agent/tools/`, because they describe the whole tree rather than belonging to one group.
- **`lib/` is imported, never installed as a command.** `.agent/tools/lib/` holds the helpers every
  tool shares, each defined once (crew-lint `single-owner`); its map is below. Import paths:
  "Imports" in `.agent/tools/AGENTS.md`.
- **PROGRESS.md has one owner, `task/task_progress.py`.** It appends every entry as
  `[YYYY-MM-DDTHH:MM:SSZ] KIND: body` (TRANSITION, METRIC, BLOCKED, WORKTREE) and reads them back;
  legacy local `[YYYY-MM-DD HH:MM:SS]` and `[YYYY-MM-DD HH:MM]` lines still parse. No other module names the file in code.
- **The installed surface is flat.** `install.sh` links basenames into `~/.agent/bin/`, so a
  basename must be unique across every subdirectory; a duplicate aborts the install instead of
  letting one link silently shadow the other. Tools resolve their siblings from
  `Path(__file__).resolve()`, which follows the installed symlink back into the repository.

| Directory | Commands | Modules (imported, not run) | Assets (read, not linked) | Purpose |
| --- | --- | --- | --- | --- |
| `task/` | `crew-agent-context.py`, `crew-default-branch.sh`, `crew-ls.py`, `crew-metric.py`, `crew-progress.py`, `crew-repo-info.py`, `crew-resolve-task-dir.py`, `crew-task.py`, `crew-task-context.py`, `crew-verify.py`, `crew-worktree.py`, `task-env.sh` | `task_bootstrap.py`, `task_status.py`, `task_state.py`, `task_progress.py`, `task_gates.py`, `task_resolve.py`, `task_report.py`, `ls_data.py`, `ls_report.py`, `task_gc.py`, `task_lock.py`, `task_artifacts.py`, `task_repo_facts.py`, `task_worktrees.py`, `task_worktree_cli.py`, `task_verify.py`, `task_verify_env.py`, `task_verify_report.py`, `task_verify_sources.py` | `transitions.json`, `next-steps.json` | Guidance context, task state, review location, status migration, resolution, gates, worktrees, repository facts, next-step routing |
| `review/` | `crew-assemble-packages.py`, `crew-diff.sh`, `crew-nightshift-e2e.py`, `crew-pr-actions.py`, `crew-review-findings.py`, `crew-review-hunks.py` | `review_bootstrap.py`, `review_vocabulary.py`, `review_models.py`, `review_parse.py`, `review_findings.py`, `review_coverage.py`, `review_layers.py`, `review_consolidate.py`, `review_render.py`, `review_report.py`, `review_records.py`, `review_workspace.py`, `review_pr_reads.py`, `review_pr_plan.py`, `review_cli.py`, `assemble_inputs.py`, `assemble_build.py` | `pr-review-threads.graphql` | Hunks and layer maps, findings, packages, PR threads, on-demand e2e runs |
| `review/nightshift/` | — | `client.py`, `location.py`, `checks.py`, `doctor.py`, `commands.py` | — | The nightshift HTTP client, the preflight probes, and the run operations |
| `evals/` | `crew-evals-compare.py`, `crew-evals-inspect.py` | `evals_query.py`, `evals_report.py`, `evals_rows.py`, `evals_diagnose.py`, `evals_sources.py`, `evals_bootstrap.py` | — | Inspect, compare, and diagnose evaluation runs |
| `memory/` | `crew-mem.py`, `crew-inbox.py` | `memory_bootstrap.py`, `memory_paths.py`, `memory_frontmatter.py`, `memory_store.py`, `memory_add.py`, `memory_search.py`, `memory_journal.py`, `memory_inbox.py`, `memory_maintenance.py` | — | Durable units and immutable observations |
| `maintenance/` | `crew-doctor.py`, `crew-lint.py`, `crew-prune.py` | `maintenance_bootstrap.py`, `lint_files.py`, `lint_catalog.py`, `lint_prompts.py`, `lint_references.py`, `lint_python.py`, `lint_writing.py`, `lint_style.py`, `prune_callers.py`, `doctor_checks.py` | — | Repository validation, the caller report, one module per lint family, and the install health check |
| `lib/` | — | `files.py`, `git.py`, `gh_reads.py`, `cli.py`, `clock.py`, `output.py`, `next_steps.py`, `workflow_yaml.py` | — | Shared helpers: one atomic write, JSON and setting read, one git/gh runner and owner/repo parser, one UTC stamp, the CLI and output contracts |
| root | — | — | `tools.json`, `TOOLS.md`, `requirements.txt` | The catalog and the dependency note |

The table is grouped by `kind`, which is what the manifest declares: a row's Commands column is
every `kind: command` entry in that directory, so `install.sh` links exactly those basenames and
nothing else.

`task-env.sh` is the one command with no `crew-` prefix: it is sourced, so `source` must find a real
file at that exact path.

`crew-mem.py`, `crew-review-findings.py`, `crew-ls.py`, `crew-task-context.py`, `crew-evals-compare.py`,
and `crew-lint.py` are argparse entry points over their modules: each parses the command line and
dispatches, and holds no command logic. Modules import each other by their namespaced name in
dependency order (`memory_paths` → `memory_frontmatter` → `memory_store` → `memory_add`/`memory_search`/
`memory_journal`/`memory_inbox` → `memory_maintenance`; `review_vocabulary` → `review_models` →
`review_findings` → `review_render`/`review_layers` → `review_coverage` → `review_report`; `task_status`
→ `task_progress` → `task_state` → `task_resolve`/`task_gates`/`ls_data` → `task_report`; `evals_query` →
`evals_report` → `evals_diagnose`/`evals_sources`; `lint_files` → `lint_catalog`/`lint_prompts`/
`lint_references`/`lint_writing`/`lint_python`, `lint_writing` → `lint_style`), so a module never imports back
into one that imports it. Import paths: "Imports" in `.agent/tools/AGENTS.md`. The entry points
re-export the names their public contract names, listed in each one's `__all__`, so
`crew-assemble-packages.py` and the tests can keep importing them from the command file rather than
reaching into a private module.

**Packages import along these edges only** (crew-lint `package-direction`; a module's package is the
directory it lives in, `lib` imports nothing from a package). `review` may read task state (PROGRESS
METRIC lines, the report check) and `maintenance` reads PROGRESS records for the prune report and the
retention policy and sizes (`task_gc.py`) for `crew-doctor.py`; `task`
never imports `review`, and nothing imports `maintenance`, `memory` or `evals` across packages:

```package-edges
task -> lib
review -> task lib
memory -> lib
evals -> lib
maintenance -> task lib
lib ->
```

**The module ceiling covers every package.** No module under `.agent/tools/` exceeds 400 lines,
wherever it lives: `crew-lint`'s `module-size` rule derives the capped set from the tree rather than
from a list, so a package added tomorrow is capped the moment its directory exists. There is no
per-package exception and no exception by filename.

## Module maps

One line per module: what it owns. Entry points (`crew-*.py`) are listed in the table above.

### `task/`

- `task_bootstrap.py`: puts `.agent/tools` and the package directories on `sys.path`
- `task_status.py`: the `## Status` contract, the review location, the typed `## Tests` rule
- `task_state.py`: the SPEC record, the status write, reconcile rules, the status migration
- `task_progress.py`: PROGRESS.md: append and read every entry (BLOCKED, METRIC and stage cost lines included)
- `task_gates.py`: the transition gates: approve, implement, close out
- `task_resolve.py`: task resolution: repo and branch to `.task-id`
- `task_report.py`: rendering task state for `crew-ls.py`, and `reconcile`
- `ls_data.py`: what `crew ls` and `--report` read: rows, the repo and state filters, stale, the `landed` lines, landing bases, `--watch`
- `ls_report.py`: `crew-ls.py --report`: opened and closed, verdicts, findings and fixed rate, stage costs and durations, tool failures
- `task_gc.py`: the retention policy (`~/.agent/config.json`), `crew-task.py gc`, the state sizes `crew-doctor.py` checks
- `task_lock.py`: the worker lock and the `crew-task.py lock|blocked` commands
- `task_artifacts.py`: bounded task artifacts: read one, render the resolved task
- `task_repo_facts.py`: the repository record a prompt reads: root, branch, head, remotes, files
- `task_worktrees.py`: worktree reads: listing, `worktree check`, `worktree pref|record`
- `task_worktree_cli.py`: worktree writes and the `crew-worktree.py` subcommands: create, sync, prune, remove
- `task_verify.py`: the `crew-verify.py` run: gates, the mirror, `--background`/`--wait` (polls every second; `CREW_VERIFY_POLL_SECONDS` overrides it)
- `task_verify_env.py`: Node pin, pass cache, result file, partial verdict
- `task_verify_report.py`: `crew-verify.py report-check` of a builder's REPORT.md
- `task_verify_sources.py`: where gates come from: CI workflows, the gates block, prose checks

### `review/`

- `review_bootstrap.py`: puts `.agent/tools` and the package directories on `sys.path`
- `review_vocabulary.py`: the closed finding vocabularies and the persona-reply classifier
- `review_models.py`: the `Finding` record and the probe score rules
- `review_parse.py`: unified-diff parsing and the generated/oversized size policy
- `review_findings.py`: the finding gates, anchors outside the diff, `normalize` and `validate`
- `review_coverage.py`: persona selection and coverage, package rules, the persist gates
- `review_layers.py`: the layer map: validation, hunk references, per-layer reports
- `review_consolidate.py`: the `consolidate` subcommand: grouping and `candidates.json`
- `review_render.py`: rendered findings, generated sections, the degraded mark, `save-out` and provenance
- `review_report.py`: `persist`: writing the report and gating it against the findings JSON
- `review_records.py`: deferred and dropped records, the cost METRIC, the outcome journal
- `review_workspace.py`: where a review writes, and the content manifest of what it read
- `review_pr_reads.py`: the read half of `crew-pr-actions.py`: running and printing PR, repo, issue and thread reads
- `review_pr_plan.py`: the write half: the `gh` mutation plan, `comments` and `check-map`
- `review_cli.py`: the `crew-review-findings.py` subcommand definitions
- `assemble_inputs.py`: what each reviewer package reads: config, personas, header, prior round
- `assemble_build.py`: building and writing the reviewer packages and their manifest record
- `review/nightshift/` (`client.py`, `location.py`, `checks.py`, `doctor.py`, `commands.py`) backs
  `crew-nightshift-e2e.py`

### `memory/`

- `memory_bootstrap.py`: puts `.agent/tools` and the package directories on `sys.path`
- `memory_paths.py`: store locations, scopes, slugs, tokens, `MemoryStoreError`
- `memory_frontmatter.py`: the unit format: scalars, frontmatter parsing and rendering
- `memory_store.py`: the FTS5 index and committing a change (`mutate`)
- `memory_add.py`: unit writes: add, cite, supersede, archive (used by `consolidate`), list, show
- `memory_search.py`: retrieval: `search` and ranked `context`
- `memory_journal.py`: journal observations: import and single-entry add
- `memory_inbox.py`: intake: `.inbox` drafts
- `memory_maintenance.py`: init, consolidate (`crew-inbox.py` fronts `memory_inbox.py`)

### `evals/`

- `evals_bootstrap.py`: puts `.agent/tools` and the package directories on `sys.path`
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
- `gh_reads.py`: the gh argv of one PR, repo or issue read and its argparse verb
- `output.py`: bounded output: the size ceiling, row limit and truncation marker
- `next_steps.py`: the next-step table; it reads the asset `task/next-steps.json`
- `workflow_yaml.py`: a CI workflow through mikefarah `yq`, else the stdlib reader

### `maintenance/`

- `maintenance_bootstrap.py`: puts `.agent/tools` and the package directories on `sys.path`
- `lint_files.py`: the in-scope document set, shared path helpers, the rule registry (`RULES`)
- `lint_catalog.py`: `tools.json`: kinds, fields, resolution, basename naming
- `lint_prompts.py`: prompt frontmatter, tool grants, the always-on budget and size ceilings
- `lint_references.py`: reference integrity in documents and the `> Next:` handoff grammar
- `lint_python.py`: the repository Python rules (module size, single owner, bootstrap, git argv)
- `lint_writing.py`: removed command forms, docstrings, narration, pipeline prose rules
- `lint_style.py`: the writing standard for prompt files (emphasis, emoji, narration, shared
  passages, glossary, vendor scope, placeholders, the closing confirmation)
- `prune_callers.py`: the caller set for a catalog command (`crew-prune.py`)
- `doctor_checks.py`: the `crew-doctor.py` checks: links, hook registrations, managed blocks (`.claude/install_blocks.py`), tools, state sizes

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
  a documented flag cannot go missing.

| Command | Output | Bound |
|---|---|---|
| `crew-agent-context.py` | JSON always | — |
| `crew-lint.py` | findings, or JSON with `--json` | — |
| `crew-prune.py` | table of caller counts, or JSON with `--json` | — |
| `crew-ls.py` | table, `--md`, or JSON with `--json`; `--report` text or JSON | `--limit`, `--max-chars` |
| `crew-doctor.py` | one screen of `ok`, `note` and `FAIL` lines; exit 1 on a `FAIL` | — |
| `crew-mem.py` | text; JSON for `search`, `context`, `list` with `--json` | `--limit`, `--max-chars` |
| `crew-review-findings.py` | text; JSON for `select`, `coverage`, `normalize` | `--max-chars` |
| `crew-review-hunks.py` | JSON summary | `--max-chars` |
| `crew-nightshift-e2e.py` | JSON always (needs a nightshift server) | `--limit`, `--max-chars` |
| `crew-evals-inspect.py` | JSON always (needs Elasticsearch) | `--limit`, `--max-chars` |
| `crew-evals-compare.py` | tables; JSON for `diagnose --json` | — |
| `crew-task-context.py` | Markdown, or JSON with `--json` | `--max-chars` |
| `crew-repo-info.py` | `key: value` lines, or JSON with `--json` | — |
| `crew-worktree.py` | the path, or JSON with `--json` | `--max-chars` |
| `crew-resolve-task-dir.py` | the path, or JSON with `--json` | — |
| `crew-pr-actions.py` | a plan or record as JSON; `--field` prints bare lines | — |
| `crew-assemble-packages.py`, `crew-metric.py`, `crew-progress.py`, `crew-task.py`, `crew-verify.py` | human text (`crew-verify.py` also writes a JSON result; `crew-task.py gc --json` lists the selected paths, each archived one with its tarball under `--apply`) | — |

- **Truncation is never silent.** `--max-chars` and `--limit` print one `[truncated: …]` marker naming
  what was dropped and which flag raises the bound; `--json` output becomes
  `{"items": [...], "total": N, "truncated": true, "hint": ...}` rather than an array that looks
  complete. The rule lives once, in `lib/output.py`; text keeps its head unless it is an append-only
  log or a report whose identity fields come last, which keeps its tail — the same rule
  `crew-task-context.py` applies per artifact.
- `tools.json` also declares the external tool surface that lint resolves. `mcp_servers` maps an MCP
  server name to the tool names this repository uses on it; `native_tools` lists the harness tool ids
  an agent may name in a `tools:` line. `crew-lint.py` reports `mcp-tool-unknown` for an
  `mcp__<server>__<tool>` reference and `tool-id-unknown` for a bare `tools:` id that neither list
  declares. A project that adds an MCP server or a new native tool id adds it here in the same change.
  `mcp-grant-policy` fails on any `mcp__` id in an agent's `tools:` line: a granted id fails the
  whole dispatch on a project without that server, so vendor tools appear only in prose, as optional.
- `crew-diff.sh` is source-only; it exports review context and intentionally does not implement an
  executable `--help`.
- `task-env.sh` is source-only; it sets `TASK_DIR` and exports `CREW_TASK_DIR` plus a tri-state
  `CREW_TASK_STATE` (`ok`, `none`, `error`). Skills source it instead of copying the resolver block.
  Gates that require a task must abort on `error` rather than treating it as `none`.
- `crew-task-context.py` is the task-artifact reader. It composes `crew-resolve-task-dir.py` with the task
  artifacts listed in `ARTIFACTS` (`task_artifacts.py`), honoring `CREW_TASK_DIR` and `--task-dir`
  before resolving so it
  cannot disagree with the shell's cached `$TASK_DIR`. It returns exit 0 with `task.found: false`
  when no task matches; resolver failures keep their nonzero exit, and resolver warnings reach
  stderr. `--artifacts` selects a subset and `--max-chars` bounds each artifact, keeping the tail for
  append-only logs and for reports whose identity fields are appended last. Agents and skills use it
  for read-side task context; write-side state still goes through `task-env.sh` and `$TASK_DIR`.
- `crew-ls.py` only reads; `crew-task.py` holds every task-state write. `crew-ls.py --status-file
  SPEC.md` is the single reader for the `## Status` contract, implemented in `task_status.py`; hooks
  and other tools import it and must not re-implement it. The listing and the reconcile report live
  in `task_report.py`, and every transition gate (`crew-task.py mark-approved`, `mark-implementing`,
  `mark-done`) lives in `task_gates.py`, so a refused transition's message
  is defined beside the check that produced it.
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
  would otherwise leave the close-out gate with nothing readable. The gate reads the verdict and the
  `Reviewed at:` commit from that one file, so the two cannot disagree, and `mark-done` prints
  which file it read (`done:` on stdout, `note:` on stderr) so a refusal is auditable.
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
- `crew-review-findings.py outcome` appends one JSONL record per decision `crew review address`
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
  `--head` instead: `crew-task.py mark-done` refuses unless the reviewed commit is an ancestor of HEAD. In PR
  mode `--head` is the GitHub head SHA, which the local checkout never fetches, so `persist` records
  it without a local existence check and requires it explicitly. A PR review is never a valid
  `mark-done` ancestor and `persist` rejects PR artifacts under a task directory.
- `crew-review-findings.py spec-context --persona <name> SPEC.md` prints the spec one persona's package
  carries (rule: "Spec in every code-mode package" in `context-tiers.md`).
  `check-packages --review-dir <task>/review/<ts> --personas <names>` rejects written `.in.md`
  packages that break that rule or embed filename-generated hunks, and reports any check it skipped
  for a missing `SPEC.md` or `hunks.json`; `persist` runs it only for a directory holding
  a `package.diff`.
- `crew-task.py mark-done --force` is a deliberate, user-invoked escape hatch that skips every
  evidence check, including review ancestry. It exists for a spec whose branch was intentionally
  rebased; it is never used by a skill on its own initiative.
- `crew-prune.py` reports catalog commands with no caller. A caller is a reference from a prompt
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
- **The reads have a command; the writes stay literal.** `crew-pr-actions.py view`, `diff`, `repo`,
  and `issue` answer the GitHub questions a prompt used to ask with `gh pr view`, `gh pr diff`,
  `gh repo view`, and `gh issue view` plus a `--jq` per call. `--field a,b` prints one bare line per
  name in the order asked and `--json` prints the record, so a field list is written once instead of
  being re-derived and re-parsed at 20 call sites; `diff` passes the patch through unchanged. A field
  gh did not return prints empty with exit 0, so a caller can test it, while a failed call exits
  nonzero carrying gh's own stderr — the same rule `crew-repo-info.py` follows for git facts.
  Mutations stay literal `gh` in the prompts: `gh pr create`, `gh pr comment`, `gh pr checkout`,
  `gh issue create`, `gh search`. A wrapper would hide the exact argv from `guard/local-pr-ref.sh`
  and `guard/destructive-git.sh`, which decide on the command text the caller wrote, so wrapping one
  turns a denial into a silent allow.
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
- `crew-assemble-packages.py <review-dir>` composes one `<persona>.in.md` package per
  reviewer from files the run already wrote, in one order: the shared head (contract, mode, hunk
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
- **Assembly decisions.** `crew-assemble-packages.py` skips a persona that cannot apply (today Prompt
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
  persona), `slice`, `skip_personas` (`{persona: why}`) and `selected`.
- **Evidence trail.** `crew-review-findings.py save-out` stores a persona's raw reply from stdin and a
  `<persona>.provenance.json` (`harness`, `agent_id|null`, `model|null`, `time`, `sha256`); `persist`
  verifies the hash when the record exists and passes a review directory without one with
  `provenance: absent (legacy)` (tamper evidence applies to new reviews only). Fewer agents than lenses
  is a `Degraded: 1 agent, N lenses` review capped at `WARN`. `consolidate --review-dir D` only GROUPS
  candidates (`raw-candidates.json`; identical file and overlapping `line`..`line_end`, never title
  similarity) into a draft `candidates.json` that `normalize` reads unchanged: every original keeps its
  label, the representative carries `group_severity`, the others get `disposition: merged`, and hunk ids
  are resolved from file:line. `consolidate --render` writes `report.md` from `consolidation.json`.
  `normalize --files ... --repo R --head H` accepts a tracked file at `H` outside the diff as a
  `non-hunk` anchor (untracked is rejected; `[blocking]` needs `line_read: true`).
- **Gates and cost.** `crew-verify.py` runs the repository's CI as its CI runs it, reading it from
  the BASE branch, by mirroring its `run:` steps. Passes are cached (`--no-cache` re-runs) by (tree
  hash, command, env, Node version); a failure is never replayed. The workflow is parsed by mikefarah `yq` when installed, else by the stdlib reader in
  `lib/workflow_yaml.py` (the last fallback), and CI workflow `run:` steps are the source whenever the repo has CI, the
  `AGENTS.md` `gates` block is the fallback for a repo with none, the repo's optional `gates.json` (in its `.agent` directory) may add gates and
  never changes a CI one (a clash prints a warning naming the gate and both commands) and stands alone
  only when it is the only source. It pins Node from the first of `.nvmrc`, `.node-version`,
  `.tool-versions`, `package.json` `engines.node` (none: "no Node pin found, using PATH"), names CI it
  cannot read ("CI not readable here (buildkite)") and falls through, and with no runnable gate prints
  the nearest `AGENTS.md`'s prose checks as "repo-declared check, run this: ..." (never run) plus
  "NOT VERIFIED" (exit 3, or 2 with `--strict`). It writes `gates.json` (`schema_version: 1`). `crew-task.py worktree pref|record` resolves where the
  worker runs (here by default) and records the one-time answer. `crew ls --watch [--interval N]`
  redraws the table (data from `ls_data.py`). The `AGENTS.md` settings (`gates`, `landing_bases`,
  `worktree`, `verify`, `e2e`) are documented in `.agent/tools/AGENTS.md`. `crew-task.py lock write|remove` owns
  `.crew-worker.lock` and `crew-task.py blocked` writes the `BLOCKED:` line `crew ls` shows. `crew-metric.py` accepts
  `stage_start stage=<implement|review>` and `stage_end stage=... tokens_reported=<n|unknown>` (tokens
  only as the harness reported them), prints the cost line, and `crew ls --cost` lists them; `crew ls
  --all` shows `landed: yes|no|unknown` for done tasks.
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
- `crew-default-branch.sh [--strict] [remote]` prints a remote's default branch. It is the single
  definition used by skills and `crew-worktree.py`: the ref walk now lives in `lib/git.py`
  (`default_branch`), and this script is a thin wrapper over `crew-repo-info.py --network`.
- `crew-repo-info.py` is the one command that answers the facts a prompt used to ask git for:
  `root`, `branch`, `head`, `head_short`, `dirty`, `changed`, `staged`, `staged_dirty`, `remote`,
  `remote_url`, `repo` (owner/repo), `repo_name`, `origin_repo`, and `default_branch`. `changed` is
  the working-tree name list and `staged` the index list; `staged_dirty` is the subset of `staged` still
  edited afterwards, which is what `crew commit`'s fast path checks: an edited-but-restaged file
  keeps the same staged names, so the list alone cannot prove a review still applies. `--field NAME`
  prints one value bare, so a prompt assigns it instead of parsing; `--json` prints the whole record;
  `--root PATH` reads another checkout, which is how a worktree's branch is read without `cd`.
  `--remote` defaults to `upstream` when it exists and `origin` otherwise, so a fork reports the repo
  its PR targets. `--network` resolves the default branch through `gh` first and `git` second;
  without it the answer comes from the local symref, so a prompt pays no round trip for a branch it
  does not need — which is why the hook scripts may call it on every write. `--diff-base` and
  `--fork-point` answer the diff question `crew-diff.sh` used to walk itself. Exit 1 when the fact
  asked for is unavailable, because a printed null with exit 0 is the silent-empty answer this
  command exists to remove.
- **Git is reached through `lib/git.py`, never through a hand-rolled call.** No Python module outside
  that file builds a `git` or `gh` argv, and no prompt runs git to learn the root, branch, remote, or
  diff base — it asks `crew-repo-info.py` or sources `crew-diff.sh`. A module imports the helper for
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
- The `.agent/tools/evals` package targets Kibana by design (`@kbn/evals-suite-*` suites found by
  their `kibana.jsonc`). The Elasticsearch tools are read-only. `crew-evals-inspect.py` and `crew-evals-compare.py` use `ES_URL`,
  plus `ES_API_KEY` or `ES_USER`/`ES_PASS`. `evals_query.py` owns that access for the compare tool
  (the HTTP call and the paged score/trace queries), `evals_rows.py` the row record built from one
  score document, `evals_report.py` the printed tables and the per-trace summary, `evals_diagnose.py`
  the sign test and the change-attribution bundle, and `evals_sources.py` the suite lookup and
  changed-path classification. `evals/compare_run.py` imports the compare tool by path and reads
  `common_prefix`, `sign_test_pvalue`, and `classify_paths` from it, which is why the entry point
  re-exports them.
- The repository is standard-library-only. `requirements.txt` documents that deliberate absence of
  third-party dependencies.

## PROGRESS.md and METRIC lines

- **PROGRESS.md** is a task's append-only event log. It is never a source for gate or status
  decisions: SPEC.md plus git and gh are. Skills may read it for resume context. Its format and
  owner are `task_progress.py` (above); `crew-progress.py` writes a transition only.
- **METRIC lines** are append-only audit records for offline analysis, never parsed for gates or
  transitions. Write one with `~/.agent/bin/crew-metric.py "$TASK_DIR" <event> [key=value ...]`; the
  events and fields are the ones `crew-metric.py` validates ("Gates and cost" above).

## Hooks

`.claude/hooks/` holds the harness hooks; `.claude/settings.json` (Claude Code) and
`.cursor/hooks.template.json` (merged into `~/.cursor/hooks.json`) register them. Every hook follows
one contract, implemented once in `.claude/hooks/lib/hook.sh`:

| Outcome | Claude Code | Cursor |
| --- | --- | --- |
| Block | exit `2`, one line on stderr, nothing on stdout | its own JSON deny on stdout, exit `0` |
| No objection | exit `0`, nothing on either stream — the harness's permission flow decides | exit `0` and nothing, same as Claude |
| Cannot judge | one line on stderr, exit `0` | one line on stderr, exit `0` |

The two mechanisms are never mixed in one run, and a Claude allow is never a
`permissionDecision: "allow"` payload, which would skip interactive approval.

One measured exception: Cursor treats *no output* from a hook registered `failClosed: true` as a
failure and blocks the command, so silence there is a block rather than a decline. The only such hook
is `guard/credentials.sh`, and it therefore answers Cursor's `beforeShellExecution` with Cursor's
documented allow payload when it has no objection. Every other hook stays silent on both harnesses.

**Fail open by default.** A missing `jq`, an unreadable payload, or an unexpected event exits `0`
after one stderr line, so a broken hook never blocks a tool call. One rule is the exception:
`guard/credentials.sh`, which alone carries `onFailure: "block"` in `.claude/settings.json` and
`failClosed: true` in `.cursor/hooks.template.json`, because a silent gap there is a credential leak.

| File | Event | Purpose |
| --- | --- | --- |
| `guard/destructive-git.sh` | Bash | `git reset --hard`, `git clean` with force, force pushes |
| `guard/local-pr-ref.sh` | Bash | `gh pr checkout` and `refs/pull/...` or `pull/<n>` refs |
| `guard/source-edit.sh` | Bash | `python -c`, `node -e`, `perl -e` and heredoc snippets that rewrite a tracked file |
| `guard/zsh-equals.sh` | Bash | a bare unquoted `=word`, which zsh reads as a command path |
| `guard/worker-tree.sh` | Bash | `git checkout`, `switch`, `restore`, `reset --hard` in a tree with a fresh `.crew-worker.lock` (advisory defence behind the always-on worktree; stale after 6 hours) |
| `guard/credentials.sh` | Bash | credential-like commits, `gh pr create` with an implied target |
| `check-write-boundary.sh` | Write, Edit | writes outside the active worktree |
| `check-task-spec-owner.sh` | Write, Edit | a `SPEC.md` written into another task's directory |
| `mode-anchor.sh` | UserPromptSubmit | the cached pipeline anchor line |
| `memory-context.sh`, `cursor-memory-context.sh` | SessionStart | bounded memory context |
| `spec-status-reconcile.sh` | SessionStart | applies the status policy, refreshes the anchor |
| `log-tool-use.sh`, `notify-idle.sh` | PostToolUse / Notification | local telemetry and the idle notification |
| `memory-capture-prompt.sh` | Stop | queues one memory review: inbox drafts, no question |

One rule per file under `guard/`, so a false positive is confined to the rule that caused it and a
reader sees one purpose per file. `lib/hook.sh` is sourced, never registered; it holds the command
normaliser every shell guard reads through and the off switches (`EL_CAPITAN_GUARDS=off`,
`EL_CAPITAN_GUARD_<NAME>=off`, documented in the README's hooks section). The normaliser prefers
`shfmt` (optional) when it is on PATH: `shfmt --to-json` parses the command and `lib/segments.jq`
turns the tree into the same segment records the awk fallback emits, so the guards never know which
parser ran; awk reads the whole command when shfmt is absent or fails on any part of it, and when
the command is over 16 KiB or nests deeply (shfmt's JSON grows with depth times size).
`evals/tools/test_hook_cases.py` runs every case through both parsers (`PARSERS_DIFFER` in
`hook_cases.py` lists the rows where awk is wrong), and CI installs the pinned shfmt with
`evals/install-shfmt.sh`. `lib/anchor.sh`
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
  worktree; Claude Code writes wherever the OS allows. `check-write-boundary.sh` allows
  `$HOME/.agent`, `$HOME/.claude`, `$HOME/.cursor`, and `/tmp` in both, so the tool is the stricter
  gate in Cursor.
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

1. Add or remove the executable in its `.agent/tools/<dir>/` subdirectory and its `tools.json` entry
   — with the matching `dir` and `kind` — in the same change. A `kind: command` entry must be
   `crew-`-prefixed and executable; a `kind: module` entry is snake_case, not executable, and never
   linked.
2. Give it `--help` at most 40 lines, or document a specific exception in `help`.
3. Assign one category and one owning skill, agent, or `repository`.
4. Declare its output contract in the same entry: `output` (`human`, `json`, `json-always`,
   `json-flag`, `json-static`), `bounded` with `list_flags` when it prints a collection, and a
   `json_smoke` invocation the test can run hermetically. Add the row to the contract table above.
5. Add a deterministic smoke command if the CLI is safe to invoke.
6. Run `python3 .agent/tools/maintenance/crew-lint.py`, the listed smoke command, and
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
