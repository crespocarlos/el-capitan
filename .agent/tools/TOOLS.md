# Agent tool catalog

Source is split by kind: `.agent/tools/` holds CLIs and their assets, and `.agent/scripts/` holds
source-only and internal helpers. `install.sh` links both into `~/.agent/bin/`, which stays a flat,
stable command surface, so installed paths do not change. `tools.json` is the machine-readable
source of truth: `tools` and `assets` live in `.agent/tools/`, and `scripts` lists the files in
`.agent/scripts/`. `crew-lint.py` validates it.

| Category | Commands | Purpose |
| --- | --- | --- |
| task | `agent-context.py`, `check-spec-typed-tests.py`, `crew-ls.py`, `default-branch.sh`, `log-metric.py`, `log-progress.py`, `manage-worktree.py`, `resolve-task-dir.py`, `task-env.sh`, `transitions.json` | Guidance context, task state, validation, worktrees, and artifacts |
| review | `dispatch_subagents.py`, `get-diff.sh`, `pr-review-actions.py`, `pr-review-threads.graphql`, `review-findings.py` | Review dispatch, diffs, findings, and PR threads |
| evals | `evals-inspect.py`, `evals-compare.py` | Inspect, compare, and diagnose evaluation runs |
| memory | `mem.py` | Durable units and immutable observations |
| maintenance | `crew-lint.py`, `crew-stats.py` | Repository validation and operational summaries |

## Contracts

- Executable Python tools expose `--help` and use exit code `2` for unavailable infrastructure or
  invalid invocation.
- `get-diff.sh` is source-only; it exports review context and intentionally does not implement an
  executable `--help`.
- `task-env.sh` is source-only; it sets `TASK_DIR` and exports `CREW_TASK_DIR` plus a tri-state
  `CREW_TASK_STATE` (`ok`, `none`, `error`). Skills source it instead of copying the resolver block.
  Gates that require a task must abort on `error` rather than treating it as `none`.
- `crew-ls.py --status-file SPEC.md` is the single reader for the `## Status` contract, implemented
  in `task_status.py`; hooks and other tools import it and must not re-implement it.
- `review-findings.py persist --files` records the reviewed paths and gates evidence against them;
  it deliberately does not compare that list with the diff. `persist` runs in three modes with no
  single base ref, so inferring one would be wrong more often than right. Tree identity is carried by
  `--head` instead: `--mark-done` refuses unless the reviewed commit is an ancestor of HEAD.
- `crew-ls.py --mark-done --force` is a deliberate, user-invoked escape hatch that skips every
  evidence check, including review ancestry. It exists for a spec whose branch was intentionally
  rebased; it is never used by a skill on its own initiative.
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
