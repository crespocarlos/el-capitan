# Agent tool catalog

Source is split by kind: `.agent/tools/` holds CLIs and their assets, and `.agent/scripts/` holds
source-only and internal helpers. `install.sh` links both into `~/.agent/bin/`, which stays a flat,
stable command surface, so installed paths do not change. `tools.json` is the machine-readable
source of truth: `tools` and `assets` live in `.agent/tools/`, and `scripts` lists the files in
`.agent/scripts/`. `crew-lint.py` validates it.

| Category | Commands | Purpose |
| --- | --- | --- |
| task | `agent-context.py`, `check-spec-typed-tests.py`, `crew-ls.py`, `default-branch.sh`, `log-metric.py`, `log-progress.py`, `manage-worktree.py`, `resolve-task-dir.py`, `task-context.py`, `task-env.sh`, `transitions.json` | Guidance context, task state, validation, worktrees, and artifacts |
| review | `dispatch_subagents.py`, `get-diff.sh`, `nightshift-e2e.py`, `pr-review-actions.py`, `pr-review-threads.graphql`, `review-findings.py`, `review-hunks.py` | Review dispatch, hunks and layer maps, findings, PR threads, and on-demand e2e runs |
| evals | `evals-inspect.py`, `evals-compare.py` | Inspect, compare, and diagnose evaluation runs |
| memory | `mem.py` | Durable units and immutable observations |
| maintenance | `crew-lint.py`, `crew-stats.py` | Repository validation and operational summaries |

## Contracts

- Executable Python tools expose `--help` and use exit code `2` for unavailable infrastructure or
  invalid invocation.
- `tools.json` also declares the external tool surface that lint resolves. `mcp_servers` maps an MCP
  server name to the tool names this repository uses on it; `native_tools` lists the harness tool ids
  an agent may name in a `tools:` line. `crew-lint.py` reports `mcp-tool-unknown` for an
  `mcp__<server>__<tool>` reference and `tool-id-unknown` for a bare `tools:` id that neither list
  declares. A project that adds an MCP server or a new native tool id adds it here in the same change.
- `get-diff.sh` is source-only; it exports review context and intentionally does not implement an
  executable `--help`.
- `task-env.sh` is source-only; it sets `TASK_DIR` and exports `CREW_TASK_DIR` plus a tri-state
  `CREW_TASK_STATE` (`ok`, `none`, `error`). Skills source it instead of copying the resolver block.
  Gates that require a task must abort on `error` rather than treating it as `none`.
- `task-context.py` is the task-artifact reader. It composes `resolve-task-dir.py` with the task
  artifacts listed in `ARTIFACTS`, honoring `CREW_TASK_DIR` and `--task-dir` before resolving so it
  cannot disagree with the shell's cached `$TASK_DIR`. It returns exit 0 with `task.found: false`
  when no task matches; resolver failures keep their nonzero exit, and resolver warnings reach
  stderr. `--artifacts` selects a subset and `--max-chars` bounds each artifact, keeping the tail for
  append-only logs and for reports whose identity fields are appended last. Agents and skills use it
  for read-side task context; write-side state still goes through `task-env.sh` and `$TASK_DIR`.
- `crew-ls.py --status-file SPEC.md` is the single reader for the `## Status` contract, implemented
  in `task_status.py`; hooks and other tools import it and must not re-implement it.
- `review-findings.py persist --files` records the reviewed paths and gates evidence against them;
  it deliberately does not compare that list with the diff. `persist` runs in three modes with no
  single base ref, so inferring one would be wrong more often than right. Tree identity is carried by
  `--head` instead: `--mark-done` refuses unless the reviewed commit is an ancestor of HEAD. In PR
  mode `--head` is the GitHub head SHA, which the local checkout never fetches, so `persist` records
  it without a local existence check and requires it explicitly. A PR review is never a valid
  `--mark-done` ancestor and `persist` rejects PR artifacts under a task directory.
- `review-findings.py spec-context --persona <name> SPEC.md` prints the spec one persona's package
  carries (rule: "Spec in every code-mode package" in `context-tiers.md`).
  `check-packages --review-dir <task>/review/<ts> --personas <names>` rejects written `.in.md`
  packages that break that rule or embed filename-generated hunks, and reports any check it skipped
  for a missing `SPEC.md` or `hunks.json`; `persist --strict` runs it only for a directory holding
  a `package.diff`.
- `crew-ls.py --mark-done --force` is a deliberate, user-invoked escape hatch that skips every
  evidence check, including review ancestry. It exists for a spec whose branch was intentionally
  rebased; it is never used by a skill on its own initiative.
- `review-hunks.py <diff> --out <dir>` writes `hunks.json`, `hunks.md`, `hunks.index.md`, and
  `package.diff` (the diff persona packages embed, generated files' hunks collapsed to one note),
  numbering every hunk `h1`, `h2`, … in diff order, including one synthetic hunk for a file with no
  textual change (binary, rename-only, mode change). It owns the ids: the persona Reading map and
  `review-findings.py coverage` share them. `hunks.md` carries index plus bodies for the
  layer-mapping pass; `hunks.index.md` is the index alone, for a persona package that already holds
  the diff. Self-contained by design — hunk parsing is project-agnostic, so it must not
  depend on another checkout. Its ids, statuses, and lines match nightshift-pr-helper's
  `parseDiff`; that parity is what lets a crew review and a nightshift review of one PR cite the
  same `h1`.
- `assemble-packages.py <review-dir> [--config <file>]` composes one `<persona>.in.md` package per
  reviewer from files the run already wrote — contract, mode, hunk reference, guidance, memory, spec,
  reading map, `package.diff`, and the consumer and prompt extras. Per-run judgement (mode text,
  consumer excerpts, prompt files, size-gate line) comes from `assemble.json` in the review directory,
  so the shared parts cannot drift between personas. Consumer excerpts and prompt files are read from
  the git index, not the working tree, and `mode_kind: "pr"` refuses both because a PR review may not
  read the local checkout at all. The persona list is derived from `review-findings.py`, and a persona
  with no `PRIMARY_KINDS` entry stops the run instead of shipping without a package.
- `nightshift-e2e.py` is the only nightshift-coupled tool: it drives the local nightshift-pr-helper
  server over HTTP for e2e runs and cannot be generalized. `doctor` is read-only and never calls
  `/api/state`, which advances the queue and can start a run. It never uses the queue or
  `post-comment` endpoints, because queued runs post a PR comment by default. Exit 3 means the
  server is unreachable.
- `default-branch.sh [--strict] [remote]` prints a remote's default branch. It is the single
  definition used by skills and `manage-worktree.py`.
- `manage-worktree.py` is stateful. Its usage output is available with `--help`; do not use smoke
  tests that create worktrees.
- `manage-worktree.py` auto-prunes only worktrees whose remote branch is gone and that are clean. It
  deletes the local branch with `git branch -d` and keeps unmerged ones; merged branches with a live
  remote are left to `crew cleanup`.
- The Elasticsearch tools are read-only. `evals-inspect.py` and `evals-compare.py` use `ES_URL`,
  plus `ES_API_KEY` or `ES_USER`/`ES_PASS`.
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

1. Add or remove the executable in `.agent/tools/` or `.agent/scripts/` and its `tools.json` entry
   in the same change.
2. Give it `--help`, or document a specific exception in `help`.
3. Assign one category and one owning skill, agent, or `repository`.
4. Add a deterministic smoke command if the CLI is safe to invoke.
5. Run `python3 .agent/tools/crew-lint.py` and the listed smoke command.

## Compatibility policy

Command basenames are public because installation creates matching `~/.agent/bin/<name>` symlinks.
Rename a command only by adding a compatible wrapper for one release cycle, documenting the
replacement in this catalog, and adding the old basename to the catalog with `status: deprecated`.
Remove the wrapper only after all repository references and installed migration cleanup entries are
gone.
