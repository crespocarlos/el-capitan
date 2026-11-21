# Spec: Centralize git access in one library

## Type: refactor
## Branch: refactor/centralize-git
## Status
DRAFTING

## Summary
`.agent/tools/lib/git.py` exists and is almost unused. Nine Python modules hand-roll
`subprocess.run(["git", ...])`, two shell scripts carry about fourteen raw git calls, and fourteen
prompt files instruct agents to run `git` directly, each inventing its own flags, error handling, and
path handling. The same three questions get answered differently depending on who asks: what is the
repository root, what is the current branch, and what is the diff base.

That produces the defects this change removes. `crew-worktree.py` has a private `git()` helper that
duplicates `run_git` with different error handling. `task_gates.py` and `task_resolve.py` ignore git's
failure and read empty output as a real answer. `memory_store.py` shells out three times to learn the
remote it could ask once. Prompt files embed shell snippets whose failure mode is a silent empty
variable, which then becomes a wrong branch name or a wrong diff.

This change adds the helpers the call sites actually need, routes every Python call through them,
folds `crew-default-branch.sh` and the base-ref logic in `crew-diff.sh` into commands that prompts
call instead of raw git, and rewrites the prompt snippets to use those commands.

Out of scope:
- Replacing `crew-diff.sh` itself: it is sourced by the reviewer and its contract is `BASE`,
  `DIFF_SOURCE`, and `CHANGED_FILES`. Its internals change; the contract does not.
- Prompt files whose git usage is documentation rather than an instruction (for example
  `crew-reviewer.md` stating what PR mode must never run).
- Adding a dependency; `subprocess` and stdlib only.

## Open questions
None.

## Decisions
- **One library, one failure mode.** Every helper raises `GitError` when git cannot answer, except
  the ones documented as returning a boolean, which return `False` only for git's own "not found"
  exit and raise for anything else. Reading empty output as an answer is the defect being removed.
- **Network reads go through `gh` first, with git as the fallback.** `gh` carries the token, so it
  works where `git` has no credential: CI, a fresh clone, an HTTPS remote, a machine with no SSH key.
  `git` remains the fallback because it works where `api.github.com` is blocked (this repository's own
  Cursor sandbox is allowlisted for `github.com` but not `api.github.com`). Measured on this machine:
  `git ls-remote` and `git remote show` succeed inside the sandbox; `gh api` there returns `Forbidden`.
  So neither path alone is portable. Every network helper tries `gh api` first, falls back to the
  equivalent git command, and raises `GitError` only when both fail — reporting both errors.
- **Local reads never use `gh`.** Root, branch, HEAD, ancestry, clean state, staged paths, and blob
  reads are local git queries with no credential involved; routing them through `gh` would be slower
  and would fail offline.
- **Prompts call commands, not git.** A prompt that shells out to git to learn the repo root, branch,
  remote, or diff base calls a `crew-*` command that prints it. Raw git stays in prompts only for
  mutations a user explicitly approved (`git commit`, `git add`, `git worktree remove`).
- **Shell scripts stay shell.** `crew-default-branch.sh` and `crew-diff.sh` are sourced and cannot
  become Python without breaking `source`; they keep working and lose duplicated logic by calling the
  Python helpers where they already shell out anyway.

## Acceptance criteria
- [ ] WHEN the tree is scanned THEN no Python module outside `lib/git.py` invokes git directly — verify: a new rule in `evals/tools/test_python_shape.py` fails on `subprocess.*(["git"` outside `lib/`, and passes.
- [ ] WHEN a git command fails THEN the caller learns it failed — verify: `python3 evals/tools/test_git_lib.py` covers detached HEAD, missing remote, missing repository, and a failing `diff`, asserting `GitError` rather than empty output.
- [ ] WHEN a read needs the network THEN `gh` is tried before git and a double failure reports both — verify: `test_git_lib.py` stubs `gh` as failing and `git` as succeeding (expects the git answer), stubs both failing (expects `GitError` naming both), and stubs `gh` succeeding (expects no git call at all).
- [ ] WHEN a prompt needs the repo root, branch, remote, or diff base THEN it calls a command — verify: `rg -n "git (rev-parse|remote get-url|branch --show-current|merge-base)" .cursor` returns no matches outside documentation-only mentions.
- [ ] WHERE the default branch is needed THEN one definition serves all callers — verify: `crew-default-branch.sh` and `manage-worktree` read the same helper, and `test_git_lib.py` asserts identical output for the same remote.
- [ ] WHEN behavior is compared THEN it is unchanged — verify: the eleven suites pass at 42, 8, 20, 13, 14, 19 plus pass for the rest; `crew-lint --budget`, `test_python_shape.py`, `test_command_names.py`, and both hook fixtures exit 0.
- [ ] WHEN the diff base is computed THEN the existing contract holds — verify: `bash .claude/hooks/fixtures/run.sh` passes and `crew-diff.sh` still exports `BASE`, `DIFF_SOURCE`, `CHANGED_FILES`.

## Tests
### Unit
- **Command**: `python3 evals/tools/test_git_lib.py` (new: every helper's success and failure path against a throwaway repository)
- **Command**: the eleven suites.
### Validation
- **Command**: `python3 .agent/tools/maintenance/crew-lint.py --budget`
- **Command**: `python3 evals/tools/test_python_shape.py`
- **Command**: `bash .claude/hooks/fixtures/run.sh` and `bash .claude/hooks/fixtures/install.sh`

## Tasks
- [ ] 1) Extend `lib/git.py` with the helpers the call sites need
  - Add `rev_parse(root, ref)` (raises when the ref does not resolve), `toplevel(root)`,
    `current_branch(root)`, `remote_url(root, name="origin")` (returns `None` only when that remote is
    absent), `is_ancestor(root, older, newer)` (bool), `is_clean(root)` (bool), `staged_paths(root)`,
    `default_branch(root, remote="origin")` implementing the same order as `crew-default-branch.sh`,
    and `blob_at(root, ref_and_path)` for the `git show :path` call sites. Keep `run_git` as the only
    place that builds a `git` argv.
  - Network helpers: `default_branch_remote(root, remote)` tries `gh api repos/{owner}/{repo} --jq
    .default_branch` then falls back to the git ref walk, and `fetch(root, remote, branch)` tries
    `gh repo sync`/`gh api` equivalents before `git fetch`. Parse `owner/repo` from the remote URL,
    handling both `git@github.com:o/r.git` and `https://github.com/o/r.git`. Local helpers never call
    `gh`.
  - Verify: `python3 evals/tools/test_git_lib.py` passes each helper's success and failure case.
- [ ] 2) Route the nine Python modules through the library
  - `task/task_gates.py`, `task/task_resolve.py`, `task/crew-worktree.py` (delete its private `git()`
    helper), `task/crew-agent-context.py`, `memory/memory_store.py` (one `remote_url` call instead of
    three), `review/review_report.py`, `review/crew-assemble-packages.py`,
    `review/crew-nightshift-e2e.py`, `evals/evals_sources.py`.
  - Verify: the new no-direct-git rule passes; the suites for each area pass.
- [ ] 3) Give prompts commands instead of git snippets
  - Add `crew-repo-info.py` printing the root, branch, remote, and default branch as JSON. Rewrite the
    prompt snippets that ask those questions: `crew-open-pr/SKILL.md` (lines 29, 39, 40, 146),
    `crew-create-issue/SKILL.md:24`, `crew-address-review/SKILL.md:43`, `crew-handoff/SKILL.md:19,64`,
    `crew-recall/SKILL.md:9`, `crew-specwriter.md:54-55`, `crew-test/SKILL.md:108`,
    `crew-e2e/SKILL.md:113-114`. Leave the diff questions to `crew-diff.sh` and the mutation examples
    as they are.
  - Verify: the prompt-grep assertion passes; `crew-repo-info.py` is registered in `tools.json` as a
    command and answers `--help` and `--json` within 40 lines.
- [ ] 4) Collapse the duplicated shell logic
  - `crew-default-branch.sh` calls `crew-repo-info.py` instead of its own ref walk and `git remote
    show`; `crew-diff.sh` keeps its sourced contract but takes the default branch and fork point from
    the same helpers. Delete whatever logic the change makes unreachable.
  - Verify: `bash .claude/hooks/fixtures/run.sh` passes; both scripts still behave identically for a
    repo with `origin`, a fork with `upstream`, and a repo with no remote.
- [ ] 5) Record the contract
  - `TOOLS.md`: the `crew-repo-info.py` entry and one line stating that Python never shells out to git
    outside `lib/git.py` and prompts ask commands, not git. `AGENTS.md` tools guide: the same rule in
    the module-layout section.
  - Verify: `crew-lint --budget` exits 0; `rg -n "crew-repo-info|lib/git" .agent/tools/TOOLS.md .agent/tools/AGENTS.md` matches.

## Hints
- `crew-worktree.py:19` has a `git()` helper with `check=False` and its own stream handling;
  `lib/git.py:run_git` already covers it. That deletion is the change in miniature.
- `memory_store.py:64-75` makes three calls (`rev-parse`, `remote`, `remote get-url`) to answer one
  question. `remote_url` answers it once, but preserve the existing preference order for `upstream`
  over `origin`.
- `task_resolve.py:23` swallows every failure with `capture_output=True` and reads `stdout` anyway.
  That is the silent-empty-variable failure the acceptance criteria target; make it raise.
- `crew-diff.sh` is **sourced**, so it cannot call a Python command that prints to stdout without
  capturing it; keep its existing `$(...)` capture shape and change only what it captures.
- Do not touch `.claude/hooks/fixtures/run.sh` git calls: the fixture exists to test hooks against
  real git, and routing it through the library under test would make it circular.
