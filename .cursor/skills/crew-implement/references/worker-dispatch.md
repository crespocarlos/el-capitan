# Worker dispatch

What the orchestrator does around the worker. Step 4 and Step 6 of `crew-implement` link here.

## Where the worker runs

This tool is project-agnostic, so a worktree is opt-in. The default is a branch off the default
branch in the current checkout (no worktree); a worktree is created only when the user asks for one
or the repo's `AGENTS.md` sets `worktree: true`. Resolve it with `crew-progress.py worktree pref`,
which prints `worktree`, `here` or `ask`. On `ask` the repo never answered: ask once per repo ("Use a
worktree for this repo? Default: no"), then record the answer so it is never asked again:

```bash
~/.agent/bin/crew-progress.py worktree record <worktree|here> "$TASK_DIR"   # marker + one WORKTREE: line in PROGRESS.md
```

Here (the default): `BRANCH_NAME` is SPEC.md's `## Branch:`; when absent derive type-prefix/slug
(<=50 chars) and confirm it. `WORK_DIR` is the tree the worker runs in; set it, then check it before
any switch:

```bash
WORK_DIR=$(~/.agent/bin/crew-repo-info.py --field root)
DEFAULT=$(~/.agent/bin/crew-default-branch.sh)
~/.agent/bin/crew-progress.py worktree check "$WORK_DIR" --task-dir "$TASK_DIR"
```

- `ok` (exit 0): cut the branch as below.
- `on-feature-branch` (exit 4): the checkout is already on a non-default branch; use it as-is, cut no
  new branch, unless the user asked for one. `BRANCH_NAME` is then the current branch.
- `dirty` (exit 5): uncommitted changes besides the task's own files; switch nothing, ask once:
  commit them, stash them, use a worktree, or stop. Then follow the answer.
- exit 2: the check itself failed; show its stderr and stop.

```bash
git -C "$WORK_DIR" fetch origin "$DEFAULT"
git -C "$WORK_DIR" switch -c "$BRANCH_NAME" "origin/$DEFAULT"   # a branch that already exists: git -C "$WORK_DIR" switch "$BRANCH_NAME"
```

Worktree: `WORK_DIR=$(~/.agent/bin/crew-worktree.py -b "$BRANCH_NAME" "origin/$(~/.agent/bin/crew-default-branch.sh)")`;
if it resolves the main tree itself (the branch is checked out there), tell the user and use here.
A dirty tree or a branch with unpublished work: stop and ask before switching.

Either way the orchestrator runs its own git as `git -C <tree> ...` and never changes the branch of a
tree a worker holds: an orchestrator `git checkout` under a running worker is how work was lost.

## The worker lock

At dispatch, once `WORK_DIR` exists, write the lock. The builder removes it on exit, and the
orchestrator removes it as soon as a worker returns or fails, so a crashed builder never leaves the
tree denied for 6 hours:

```bash
~/.agent/bin/crew-progress.py lock write "$WORK_DIR" --task "$(basename "$TASK_DIR")"
~/.agent/bin/crew-progress.py lock remove "$WORK_DIR"     # builder's last step; the orchestrator's too, when a worker returns or fails
```

The lock is `<tree root>/.crew-worker.lock` (`task=<id>`, `started=<epoch>`), excluded from git
through `.git/info/exclude`. While it is fresh (younger than 6 hours) the guard hook
`.claude/hooks/guard/worker-tree.sh` denies `git checkout`, `git switch`, `git restore` and `git
reset --hard` in that tree, whether run from it, as `git -C <path>` or after a leading `cd <path> &&`.
A stale lock (a worker that died) allows them. The denial gives the lock's age and says to ask the
user before removing the lock. The guard is defence in depth and now protects the
main tree when no worktree is used; on a harness without hooks (Codex, plain CLI) it is advisory.

The builder is exempt from its own lock: it exports `CREW_WORKER_TASK=<the lock's task id>` (the
`basename` of `TASK_DIR`) and prefixes its own `git checkout|switch|restore` with the same
assignment, because a hook sees the command and the harness environment but not a variable exported
inside the builder's shell. A different id, an empty value or an unset variable still denies.

## Messages that arrive during a worker run

This section owns the routing sentence; `crew-implement` and `crew-reviewer` only point here. The
user's message goes to the worker (or persona), not to the orchestrator, but say so only when the
harness reports a run in flight. `<id>` is the agent id the harness reported for that run. In the
first reply after it start with one line:
`Your message reached worker <id>, not me; I will re-apply it at the next stage.`
Then act on the message at the next stage. No file is written for it.

## When the run pauses or stops

An autonomous run that pauses or stops (open question, scope change, stacked base, rejected report,
blocked gate) records why, once, before the final message:

```bash
~/.agent/bin/crew-progress.py blocked "$TASK_DIR" "<reason in one line>"
```

`crew ls` shows the line until the next stage writes its own transition.

## The worker prompt

Pass the task delta only: the unchecked tasks with their verify lines (a guideline of about 400
words, not a gate) and the `SPEC.md` path, plus `TASK_DIR`, `WORK_DIR`, `RECALLED_PATTERNS` and
`TASK_RANGE`. The builder file (`~/.cursor/agents/crew-builder.md`) owns the rules, the report shape
and the quality gates, so the prompt names its path and does not paste it: pasted rules drift from
the file and are paid for in every worker.

## The stage cost line

Tokens exist only in the harness, so record what it reported when the workers finish:

```bash
~/.agent/bin/crew-metric.py "$TASK_DIR" stage_end stage=implement workers=<n> tokens_reported=<n|unknown>
```

It validates the keys, appends the line to PROGRESS.md and prints `implement: 3 workers, 410k tokens`;
show that line in the handoff. Use `unknown` when the harness gives nothing, never an estimate.
`crew ls --cost` lists the lines of every task. Review's counterpart is in
`~/.cursor/agents/references/stage-rules.md`.
