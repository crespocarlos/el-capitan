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
| `task/` | `crew-agent-context.py`, `crew-default-branch.sh`, `crew-ls.py`, `crew-metric.py`, `crew-progress.py`, `crew-resolve-task-dir.py`, `crew-task-context.py`, `crew-worktree.py`, `task-env.sh` | `task_status.py`, `task_state.py`, `task_resolve.py`, `task_report.py`, `task_gates.py`, `task_typed_tests.py`, `task_artifacts.py` | `transitions.json` | Guidance context, task state, resolution, gates, worktrees |
| `review/` | `crew-assemble-packages.py`, `crew-diff.sh`, `crew-nightshift-e2e.py`, `crew-pr-actions.py`, `crew-review-findings.py`, `crew-review-hunks.py` | `review_findings.py`, `review_layers.py`, `review_personas.py`, `review_report.py` | `pr-review-threads.graphql` | Hunks and layer maps, findings, packages, PR threads, on-demand e2e runs |
| `evals/` | `crew-evals-compare.py`, `crew-evals-inspect.py` | `evals_query.py`, `evals_report.py`, `evals_diagnose.py`, `evals_sources.py` | — | Inspect, compare, and diagnose evaluation runs |
| `memory/` | `crew-mem.py` | `memory_store.py`, `memory_units.py`, `memory_recall.py`, `memory_maintenance.py` | — | Durable units and immutable observations |
| `maintenance/` | `crew-lint.py` | `lint_catalog.py`, `lint_naming.py`, `lint_prompts.py`, `lint_references.py`, `lint_progress.py`, `lint_budget.py`, `lint_files.py` | — | Repository validation, one module per lint family |
| `lib/` | — | `files.py`, `git.py`, `cli.py` | — | Shared helpers: one atomic write, one git/gh runner, the CLI contract |
| root | — | — | `tools.json`, `TOOLS.md`, `requirements.txt` | The catalog and the dependency note |

The table is grouped by `kind`, which is what the manifest declares: a row's Commands column is
every `kind: command` entry in that directory, so `install.sh` links exactly those basenames and
nothing else.

`task-env.sh` is the one command with no `crew-` prefix: it is sourced, so `source` must find a real
file at that exact path.

`crew-mem.py`, `crew-review-findings.py`, `crew-ls.py`, `crew-task-context.py`, `crew-evals-compare.py`,
and `crew-lint.py` are argparse entry points over their modules: each parses the command line and
dispatches, and holds no command logic. Modules import each other by their namespaced name in
dependency order (`memory_store` → `memory_units` → `memory_recall` → `memory_maintenance`;
`review_findings` → `review_personas`/`review_layers` → `review_report`; `task_state` →
`task_resolve`/`task_typed_tests` → `task_gates`/`task_report`/`task_artifacts`; `evals_query` →
`evals_report` → `evals_diagnose`/`evals_sources`; `lint_files` → `lint_naming`/`lint_budget` →
`lint_catalog`/`lint_prompts`/`lint_references` → `lint_progress`), so a module never imports back
into one that imports it. A hyphenated entry point cannot be a module, so it puts its own directory
and `.agent/tools` on `sys.path` once, which is also what makes `lib` importable. The entry points
re-export the names their public contract names, so `crew-assemble-packages.py` and the tests can
keep importing them from the command file rather than reaching into a private module.

The one structural rule the split enforces: no module in `task/`, `maintenance/`, or `evals/`
exceeds 200 lines (`evals/tools/test_python_shape.py` reports `long-module`), and the
`crew-lint.py` entry point stays under 120 because each lint family lives in its own `lint_*`
module.

## Contracts

- Executable Python tools expose `--help` and use exit code `2` for unavailable infrastructure or
  invalid invocation.
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
- `crew-review-findings.py` records two optional fields on a finding — `kind` (what sort of defect: its
  values are `KINDS` in the tool, `security`, `correctness`, `reliability`, `documentation`, `testing`,
  `other`) and `validation` (one sentence on what a `verified: true` check read and concluded, required
  under `--strict` in every mode).
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
  for a missing `SPEC.md` or `hunks.json`; `persist --strict` runs it only for a directory holding
  a `package.diff`.
- `crew-ls.py --mark-done --force` is a deliberate, user-invoked escape hatch that skips every
  evidence check, including review ancestry. It exists for a spec whose branch was intentionally
  rebased; it is never used by a skill on its own initiative.
- `crew-pr-actions.py` is the only tool that mutates GitHub. `--execute` is the single mutation
  switch: `reply` and `resolve` without it print a plan and exit 0 without invoking `gh`, and
  `--dry-run` names that behavior explicitly (the two are mutually exclusive). The plan's `command`
  field is the exact `gh` argv, so an operator can read or run it by hand. `fetch` takes `--dry-run`
  as well and defaults `--query` to the `pr-review-threads.graphql` asset, so the query text has one
  source.
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
  server is unreachable.
- `crew-default-branch.sh [--strict] [remote]` prints a remote's default branch. It is the single
  definition used by skills and `crew-worktree.py`.
- `crew-worktree.py` is stateful. Its usage output is available with `--help`; do not use smoke
  tests that create worktrees.
- `crew-worktree.py` auto-prunes only worktrees whose remote branch is gone and that are clean. It
  deletes the local branch with `git branch -d` and keeps unmerged ones; merged branches with a live
  remote are left to `crew cleanup`.
- The Elasticsearch tools are read-only. `crew-evals-inspect.py` and `crew-evals-compare.py` use `ES_URL`,
  plus `ES_API_KEY` or `ES_USER`/`ES_PASS`. `evals_query.py` owns that access for the compare tool
  (the HTTP call and the paged score/trace queries), `evals_report.py` the printed tables and the
  per-trace summary, `evals_diagnose.py` the sign test and the change-attribution bundle, and
  `evals_sources.py` the suite lookup and changed-path classification. `evals/compare_run.py`
  imports the compare tool by path and reads `common_prefix`, `sign_test_pvalue`, and
  `classify_paths` from it, which is why the entry point re-exports them.
- The repository is standard-library-only. `requirements.txt` documents that deliberate absence of
  third-party dependencies.

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
2. Give it `--help`, or document a specific exception in `help`.
3. Assign one category and one owning skill, agent, or `repository`.
4. Add a deterministic smoke command if the CLI is safe to invoke.
5. Run `python3 .agent/tools/maintenance/crew-lint.py` and the listed smoke command.

## Compatibility policy

Command basenames are public because installation creates matching `~/.agent/bin/<name>` symlinks.
A rename is therefore a breaking change: apply it in one change — the new basename, every caller in
this repository, the catalog entry, and this document — because no alias cycle exists. `install.sh`
links exactly the catalog's `kind: command` entries and `prune_retired_tool_links` removes any
`~/.agent/bin` link whose target is in this tool tree but whose basename is no longer cataloged, so
the stale link goes on the next install.
