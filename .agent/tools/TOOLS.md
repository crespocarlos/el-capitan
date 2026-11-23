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
  tool shares — `files.py` (`atomic_write`, `read_json`), `git.py` (`run_git`, `gh`, the dirty and
  conflict helpers), and `cli.py` (the parser factory and `fail`). A tool adds `.agent/tools` to
  `sys.path` and imports `lib.files`, so one `atomic_write` exists in the whole tree.
- **The installed surface is flat.** `install.sh` links basenames into `~/.agent/bin/`, so a
  basename must be unique across every subdirectory; a duplicate aborts the install instead of
  letting one link silently shadow the other. Tools resolve their siblings from
  `Path(__file__).resolve()`, which follows the installed symlink back into the repository.

| Directory | Commands | Modules (imported, not run) | Assets (read, not linked) | Purpose |
| --- | --- | --- | --- | --- |
| `task/` | `crew-agent-context.py`, `crew-default-branch.sh`, `crew-ls.py`, `crew-metric.py`, `crew-progress.py`, `crew-repo-info.py`, `crew-resolve-task-dir.py`, `crew-task-context.py`, `crew-worktree.py`, `task-env.sh` | `task_status.py`, `task_state.py`, `task_review.py`, `task_normalize.py`, `task_resolve.py`, `task_report.py`, `task_gates.py`, `task_typed_tests.py`, `task_artifacts.py`, `task_repo_facts.py`, `task_worktrees.py`, `task_worktree_create.py`, `task_worktree_cli.py`, `task_worktree_prune.py` | `transitions.json` | Guidance context, task state, review location, status migration, resolution, gates, worktrees, repository facts |
| `review/` | `crew-assemble-packages.py`, `crew-diff.sh`, `crew-nightshift-e2e.py`, `crew-pr-actions.py`, `crew-review-findings.py`, `crew-review-hunks.py` | `review_findings.py`, `review_vocabulary.py`, `review_models.py`, `review_gates.py`, `review_layers.py`, `review_map.py`, `review_personas.py`, `review_classify.py`, `review_coverage.py`, `review_report.py`, `review_persist_gates.py`, `review_parse.py`, `review_limits.py`, `assemble_config.py`, `assemble_common.py`, `assemble_map.py`, `assemble_files.py`, `assemble_personas.py`, `assemble_build.py` | `pr-review-threads.graphql` | Hunks and layer maps, findings, packages, PR threads, on-demand e2e runs |
| `review/nightshift/` | — | `client.py`, `location.py`, `checks.py`, `doctor.py`, `commands.py` | — | The nightshift HTTP client, the preflight probes, and the run operations |
| `evals/` | `crew-evals-compare.py`, `crew-evals-inspect.py` | `evals_query.py`, `evals_report.py`, `evals_rows.py`, `evals_diagnose.py`, `evals_sources.py` | — | Inspect, compare, and diagnose evaluation runs |
| `memory/` | `crew-mem.py` | `memory_store.py`, `memory_paths.py`, `memory_scalars.py`, `memory_frontmatter.py`, `memory_index.py`, `memory_commit.py`, `memory_add.py`, `memory_units.py`, `memory_cite.py`, `memory_search.py`, `memory_context.py`, `memory_journal.py`, `memory_journal_add.py`, `memory_recall.py`, `memory_inbox.py`, `memory_ingest.py`, `memory_maintenance.py` | — | Durable units and immutable observations |
| `maintenance/` | `crew-lint.py`, `crew-prune.py` | `lint_catalog.py`, `lint_naming.py`, `lint_prompts.py`, `lint_references.py`, `lint_progress.py`, `lint_budget.py`, `lint_files.py`, `prune_callers.py` | — | Repository validation and the caller report, one module per lint family |
| `lib/` | — | `files.py`, `git.py`, `git_remote.py`, `cli.py` | — | Shared helpers: one atomic write, one git/gh runner, the CLI contract |
| root | — | — | `tools.json`, `TOOLS.md`, `requirements.txt` | The catalog and the dependency note |

The table is grouped by `kind`, which is what the manifest declares: a row's Commands column is
every `kind: command` entry in that directory, so `install.sh` links exactly those basenames and
nothing else.

`task-env.sh` is the one command with no `crew-` prefix: it is sourced, so `source` must find a real
file at that exact path.

`crew-mem.py`, `crew-review-findings.py`, `crew-ls.py`, `crew-task-context.py`, `crew-evals-compare.py`,
and `crew-lint.py` are argparse entry points over their modules: each parses the command line and
dispatches, and holds no command logic. Modules import each other by their namespaced name in
dependency order (`memory_paths` → `memory_scalars` → `memory_frontmatter` → `memory_index` →
`memory_commit` → `memory_add`/`memory_units`/`memory_cite` → `memory_search`/`memory_context`/
`memory_journal` → `memory_inbox`/`memory_ingest`/`memory_maintenance`, with `memory_store` the
façade that re-exports all of it; `review_vocabulary` → `review_models` → `review_gates` →
`review_findings` → `review_classify`/`review_coverage`/`review_map` → `review_layers`/
`review_personas` → `review_persist_gates` → `review_report`; `task_state` →
`task_resolve`/`task_typed_tests` → `task_gates`/`task_report`/`task_artifacts`; `evals_query` →
`evals_report` → `evals_diagnose`/`evals_sources`; `lint_files` → `lint_naming`/`lint_budget` →
`lint_catalog`/`lint_prompts`/`lint_references` → `lint_progress`), so a module never imports back
into one that imports it. A hyphenated entry point cannot be a module, so it puts its own directory
and `.agent/tools` on `sys.path` once, which is also what makes `lib` importable. The entry points
re-export the names their public contract names, so `crew-assemble-packages.py` and the tests can
keep importing them from the command file rather than reaching into a private module.

**The module ceiling covers every package.** No module under `.agent/tools/` exceeds 200 lines,
wherever it lives: `test_python_shape.py` derives the capped set from the tree rather than from a
list, so a package added tomorrow is capped the moment its directory exists. There is no per-package
exception and no exception by filename.

The one structural rule the split enforces: no module in `task/`, `maintenance/`, or `evals/`
exceeds 200 lines (`evals/tools/test_python_shape.py` reports `long-module`), and the
`crew-lint.py` entry point stays under 120 because each lint family lives in its own `lint_*`
module.

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
| `crew-ls.py` | table, `--tsv`, `--md`, or JSON with `--json` | `--limit`, `--max-chars` |
| `crew-mem.py` | text; JSON for `search`, `context`, `list` with `--json` | `--limit`, `--max-chars` |
| `crew-review-findings.py` | text; JSON for `select`, `coverage`, `normalize`, `validate-map` | `--max-chars` |
| `crew-review-hunks.py` | JSON summary | `--max-chars` |
| `crew-nightshift-e2e.py` | JSON always (needs a nightshift server) | `--limit`, `--max-chars` |
| `crew-evals-inspect.py` | JSON always (needs Elasticsearch) | `--limit`, `--max-chars` |
| `crew-evals-compare.py` | tables; JSON for `diagnose --json` | — |
| `crew-task-context.py` | Markdown, or JSON with `--json` | `--max-chars` |
| `crew-repo-info.py` | `key: value` lines, or JSON with `--json` | — |
| `crew-worktree.py` | the path, or JSON with `--json` | `--max-chars` |
| `crew-resolve-task-dir.py` | the path, or JSON with `--json` | — |
| `crew-pr-actions.py` | a plan or record as JSON; `--field` prints bare lines | — |
| `crew-assemble-packages.py`, `crew-metric.py`, `crew-progress.py` | human text | — |

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
- `crew-ls.py --status-file SPEC.md` is the single reader for the `## Status` contract, implemented
  in `task_status.py`; hooks and other tools import it and must not re-implement it. The listing and
  the `--reconcile` report live in `task_report.py`, and every transition gate — `--mark-approved`,
  `--mark-implementing`, `--mark-done` — lives in `task_gates.py`, so a refused transition's message
  is defined beside the check that produced it.
- **The status token is canonical and normalized on read.** `DRAFTING`, `APPROVED`, `IMPLEMENTING`,
  `ON-HOLD`, `DONE` are the five states; `ABANDONED` is a user-only side state the store may hold.
  `task_status.head` uppercases and strips trailing punctuation, so `done`, `Done`, and `DONE.` are
  one token, and `task_status.token` rejects anything outside that set with a message naming it.
  A writer must emit the canonical spelling: lowercase is a legacy value, never a second state.
  `crew-ls.py --normalize-status [--apply]` previews and applies the one-shot rewrite of every stored
  legacy token across `--tasks-dir`, reporting each file and exiting 0 when a second run finds
  nothing left to change.
- **A task's review may live outside the task directory.** `task_review.py` resolves it: the task's
  own `REVIEW.md` when present, otherwise the directory `review_dir` in the task's `run.json` names.
  Both `run.json` writers record it — `review_workspace.claim` when the review directory is created,
  and `persist` on every write — because a PR-mode review persists to a temp directory by design and
  would otherwise leave the close-out gate with nothing readable. The gate reads the verdict and the
  `Reviewed at:` commit from that one file, so the two cannot disagree, and `--mark-done` prints
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
  rejected, as is a `confidence_from` equal to the score, which records nothing. The score is the
  reviewer's belief, never a severity, and is never summed into a review-level number.
  `normalize` and `persist` apply those gates by default; `--lenient` is the escape and `--strict`
  is a no-op alias kept one cycle so a script written against the old default still runs.
- `crew-review-findings.py outcome` appends one JSONL record per decision `crew review address`
  makes; `outcomes --review-dir <dir> --acted <id> …` reads them back and exits 1 naming any acted
  finding with no record, which is what fails a summary that skipped one. `outcome --confidence N
  --confidence-from M --validation "<the read>"` records the score a decision was made under when it
  raised one; the pair is required together and a rise is refused without the sentence naming the read
  that settled it, while an unchanged pair is refused as not a raise, so the journal's authoritative
  score carries the same halves a persisted finding does. `crew-review-stats.py` joins the decision's
  score rather than the score the finding arrived with, and reads a record only for the review it
  names, so one review's raise cannot band a sibling review's finding. Two journal shapes exist
  (`<review>/outcomes.jsonl` and `<task>/review/outcomes.jsonl`) because the path follows the
  directory the caller named, so both are read; a relative `review_dir` resolves against its own
  journal. Precision over a corpus this thin is meaningless without that denominator, which is why
  `crew-review-stats.py` prints it beside every ratio.
- `crew-review-stats.py --tasks-dir <store>` measures a recorded corpus: findings by label, the
  required field each one is missing, the confidence distribution with the fix rate per band, and
  precision per persona as `fixed / (fixed + rejected)` with the decided count and the `unrecorded`
  count beside it. A finding with no usable band — written before the score existed, or carrying a
  value outside 1-5 — is reported as `unscored` and never folded into a band, because a zero-filled
  distribution reads as a measurement nobody made. The `unscored` row names both causes rather than
  attributing a hand-edited value to history.
  `--json` is the machine form, `--limit` bounds the review list, `--max-chars` the whole output. A
  corpus with no outcome says so instead of printing `0.00`, and an unreadable `--tasks-dir` exits 2
  rather than reporting zero findings.
- `crew-review-findings.py persist --files` records the reviewed paths and gates evidence against them;
  it deliberately does not compare that list with the diff. `persist` runs in three modes with no
  single base ref, so inferring one would be wrong more often than right. Tree identity is carried by
  `--head` instead: `--mark-done` refuses unless the reviewed commit is an ancestor of HEAD. In PR
  mode `--head` is the GitHub head SHA, which the local checkout never fetches, so `persist` records
  it without a local existence check and requires it explicitly. A PR review is never a valid
  `--mark-done` ancestor and `persist` rejects PR artifacts under a task directory.
- `crew-review-findings.py spec-context --persona <name> SPEC.md` prints the spec one persona's package
  carries (rule: "Spec in every code-mode package" in `context-tiers.md`).
  `check-packages --review-dir <task>/review/<ts> --personas <names>` rejects written `.in.md`
  packages that break that rule or embed filename-generated hunks, and reports any check it skipped
  for a missing `SPEC.md` or `hunks.json`; `persist` runs it only for a directory holding
  a `package.diff`.
- `crew-ls.py --mark-done --force` is a deliberate, user-invoked escape hatch that skips every
  evidence check, including review ancestry. It exists for a spec whose branch was intentionally
  rebased; it is never used by a skill on its own initiative.
- `crew-prune.py` reports catalog commands with no caller. A caller is a reference from a prompt
  (rules, agents, skills, `AGENTS.md`, the templates), a hook, `install.sh`, or another tool; the
  catalog page and tests are counted in their own columns and never decide the verdict, because
  `TOOLS.md` names every command by construction and a test proves a command runs, not that the
  pipeline asks for it. `uncalled` — no reference at all — is the only automatic judgment and makes
  the command exit 1; `test-only` is listed for a person to decide. Journal mentions appear beside the
  verdict, never instead of it. Pruning stays a human decision: this report deletes nothing.
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
- `crew-assemble-packages.py <review-dir> [--config <file>]` composes one `<persona>.in.md` package per
  reviewer from files the run already wrote — contract, mode, hunk reference, guidance, memory, spec,
  reading map, `package.diff`, and the consumer and prompt extras. Per-run judgement (mode text,
  consumer excerpts, prompt files, size-gate line) comes from `assemble.json` in the review directory,
  so the shared parts cannot drift between personas. Consumer excerpts and prompt files are read from
  the git index, not the working tree, and `mode_kind: "pr"` refuses both because a PR review may not
  read the local checkout at all. The persona list is derived from `crew-review-findings.py`, and a persona
  with no `PRIMARY_KINDS` entry stops the run instead of shipping without a package.
- `crew-nightshift-e2e.py` is the only nightshift-coupled tool: it drives the local nightshift-pr-helper
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
  the working-tree name list and `staged` the index list, which is what `crew test` falls back to
  when `crew-diff.sh` reports no committed change; `staged_dirty` is the subset of `staged` still
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
  and uses git alone, while the remote questions (default branch, remote tip, fetch, compare) live in
  `lib/git_remote.py`, try `gh` first because it carries the authentication, and fall back to git,
  raising `GitError` that names both failures. `git.py` re-exports them, and `git_remote` reads the
  runner through `git.py`'s globals, so a caller that patches `run_git` or `gh` is the one they call.
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
  remote are left to `crew cleanup`.
- The Elasticsearch tools are read-only. `crew-evals-inspect.py` and `crew-evals-compare.py` use `ES_URL`,
  plus `ES_API_KEY` or `ES_USER`/`ES_PASS`. `evals_query.py` owns that access for the compare tool
  (the HTTP call and the paged score/trace queries), `evals_rows.py` the row record built from one
  score document, `evals_report.py` the printed tables and the per-trace summary, `evals_diagnose.py`
  the sign test and the change-attribution bundle, and `evals_sources.py` the suite lookup and
  changed-path classification. `evals/compare_run.py` imports the compare tool by path and reads
  `common_prefix`, `sign_test_pvalue`, and `classify_paths` from it, which is why the entry point
  re-exports them.
- The repository is standard-library-only. `requirements.txt` documents that deliberate absence of
  third-party dependencies.

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
| `guard/destructive-git.sh` | Bash | `git reset --hard`, `git clean -f`, force pushes, escaped `gh`/`git` |
| `guard/local-pr-ref.sh` | Bash | `gh pr checkout` and `pull/<n>` reads |
| `guard/source-edit.sh` | Bash | Python snippets that rewrite a tracked file |
| `guard/zsh-equals.sh` | Bash | a bare unquoted `=word`, which zsh reads as a command path |
| `guard/credentials.sh` | Bash | credential-like commits, `gh pr create` with an implied target |
| `check-write-boundary.sh` | Write, Edit | writes outside the active worktree |
| `check-task-spec-owner.sh` | Write, Edit | a `SPEC.md` written into another task's directory |
| `mode-anchor.sh` | UserPromptSubmit | the cached pipeline anchor line |
| `memory-context.sh`, `cursor-memory-context.sh` | SessionStart | bounded memory context |
| `spec-status-reconcile.sh` | SessionStart | applies the status policy, refreshes the anchor |
| `session-event.sh`, `log-tool-use.sh`, `notify-idle.sh` | lifecycle / PostToolUse / Notification | local telemetry and the idle notification |
| `memory-capture-prompt.sh` | Stop | asks once for a memory candidate |

One rule per file under `guard/`, so a false positive is confined to the rule that caused it and a
reader sees one purpose per file. `lib/hook.sh` is sourced, never registered, and `lib/anchor.sh`
holds the anchor line `spec-status-reconcile.sh` computes and `mode-anchor.sh` reprints.

The review-address gate is a `permissions.ask` rule in `.claude/settings.json`, not a hook: the
harness asks before a review-address run writes anything, so no state file, marker, or
approval-recording hook exists to go stale.

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
   `python3 evals/tools/test_command_names.py`.

## Compatibility policy

Command basenames are public because installation creates matching `~/.agent/bin/<name>` symlinks.
A rename is therefore a breaking change: apply it in one change — the new basename, every caller in
this repository, the catalog entry, and this document — because no alias cycle exists. `install.sh`
links exactly the catalog's `kind: command` entries and `prune_retired_tool_links` removes any
`~/.agent/bin` link whose target is in this tool tree but whose basename is no longer cataloged, so
the stale link goes on the next install.
