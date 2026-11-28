# Worker dispatch

What the orchestrator does around a worker. Step 3 and Step 5 of `crew-implement` link here; the
router's `crew resolve PR` dispatch follows the reliability rules too. Inputs: `TASK_DIR` (the task
directory) and `WORK_DIR` (the tree the worker runs in, line one of `prepare-implement`).

## Dispatch reliability

Both workers, `crew-builder` and the read-only `crew-pr-resolver`, are background subagents.

- Without native persona or worker dispatch, use the documented degraded fallback, never an
  orchestrator subagent.
- Preserve model inheritance: no `model` in agent frontmatter.
- Launch asynchronously in Cursor, because its synchronous turn limit (about 30 seconds) ends a
  healthy run.
- Pass the task directory and worktree paths in the launch prompt; read the durable report
  (`SPEC.md`, `REPORT.md`, the resolver's plan) once the run ends.
- Retry once, asynchronously, when a dispatch ends without its durable report (a resolver reply
  without the Step 6 table has none); never restart a task that already produced one.

## Where the worker runs

This tool is project-agnostic, so a worktree is opt-in. The default is a branch off the default
branch in the current checkout (no worktree); a worktree is created only when the user asks for one
or the repo's `AGENTS.md` sets `worktree: true`. `prepare-implement` reads that choice (`crew-task.py
worktree pref`: `worktree`, `here` or `ask`). On `ask` the repo never answered, and it stops with exit
1 naming the question: ask once per repo ("Use a worktree for this repo? Default: no") and run it
again with `--where worktree|here`, which records the answer (a marker and one `WORKTREE:` line in
PROGRESS.md) so it is never asked again.

The branch is SPEC.md's `## Branch:`; when absent derive type-prefix/slug (<=50 chars), confirm it,
and pass `--branch`. Here, `prepare-implement` checks the checkout first (`worktree check`):

- `ok`: it fetches the default branch and cuts the branch from it (or switches to it when it exists).
- `on-feature-branch`: the checkout is already on a non-default branch; it is used as-is. A
  `--branch` naming another branch stops with exit 1 naming both: ask whether to switch first, use a
  worktree, or drop `--branch`.
- `dirty` (exit 1): uncommitted changes besides the task's own files; nothing is switched. Ask once:
  commit them, stash them, use a worktree (`--where worktree`), or stop. Then follow the answer.

With a worktree it reuses the one holding the branch, else creates `<repo>-<branch>` beside the
checkout from the default branch. A branch with unpublished work: stop and ask before switching.

Either way the orchestrator runs its own git as `git -C <tree> ...` and never changes the branch of a
tree a worker holds, because a checkout under a running worker discards the worker's edits.

## The worker lock

The orchestrator writes the lock at dispatch (crew-implement Step 5), after the bootstrap, so a setup
command never runs in a locked tree and a failed `prepare-implement` leaves none. The builder removes
it on exit, and the orchestrator removes it as soon as a worker returns or fails, so a crashed builder
never leaves the tree denied for 6 hours:

```bash
~/.agent/bin/crew-tool.py task-lock write "$WORK_DIR" "$(basename "$TASK_DIR")"    # Step 5, before the first dispatch
~/.agent/bin/crew-tool.py task-lock remove "$WORK_DIR" "$(basename "$TASK_DIR")"   # builder's last step; the orchestrator's too, when a worker returns or fails
```

The lock is `<tree root>/.crew-worker.lock` (`task=<id>`, `started=<epoch>`), excluded from git
through `.git/info/exclude`. While it is fresh (younger than 6 hours) the guard hook
`.claude/hooks/guard/shell.sh` (its worker-tree rule) denies `git checkout`, `git switch`, `git restore` and `git
reset --hard` in that tree, whether run from it, as `git -C <path>` or after a leading `cd <path> &&`.
A stale lock (a worker that died) allows them. The denial gives the lock's age and says to ask the
user before removing the lock. The guard is defence in depth and protects the main tree when no
worktree is used; on a harness without hooks (Codex, plain CLI) it is advisory.

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
~/.agent/bin/crew-tool.py task-transition block "$TASK_DIR" --reason "<reason in one line>"
```

`crew ls` shows the line until the next stage writes its own transition.

## The worker prompt

`prepare-implement` writes it as `$TASK_DIR/dispatch/builder.md` (a batch: `builder.<first>-<last>.md`):
the unchecked tasks with their verify lines, `TASK_DIR`, `WORK_DIR`, the `SPEC.md` path,
`RECALLED_PATTERNS`, `TASK_RANGE`, and the guidance for the files they name, ranked for a builder.
The builder file
(`~/.claude/agents/crew-builder.md`) owns the rules, the report shape and the verification commands,
so the prompt names its path: pasted rules drift and are paid for per worker. The prompt's first line is `crew-task: <TASK_DIR>`: the subagent-stop hook appends the worker's `agent_end` METRIC to that task
(Claude Code: its transcript's tokens; Cursor: duration and tool calls, tokens unknown), which the
cost line below then reports, and saves the builder's reply as that task's `REPORT.md`. A `TASK_RANGE: <first>-<last>` line right under it makes
the reply a part report, and `TASK_RANGE: <first>-<last> final` both the part report and `REPORT.md`.

## Batching for large specs

When the spec has more than 8 unchecked tasks, `prepare-implement` splits them into consecutive
batches of at most 6, never ending one inside a declared atomic group (`> Tasks 4 and 5 are atomic`,
`Tasks 4-6`, `3, 4 and 5`; numbers are `T<n>` labels when every task has one), one prompt and one
fresh worker per batch. An atomic line it cannot read stops it with exit 1 naming the line: rewrite it
in one of those forms. Each prompt's header carries one `TASK_RANGE: <first>-<last>`
line beside `crew-task:`; the last batch's says `final`. The save reads that line, and only from the
header, so name earlier ranges elsewhere in other words. Launch the next batch only after the previous
batch's `REPORT.part-*.md` is saved and reports no failed task; on a failure, stop and go to Step 6
with that part report. The final batch runs the Completion Protocol
and returns the merged report (the part reports' task results, decisions, and verification
results), which is saved as its part report and as `REPORT.md`.

## Recording the branch

`prepare-implement` runs `mark-implementing` with `--branch` and `--root` set to the branch and the
tree it just settled, not the drafting checkout it runs from. It records the branch actually being
implemented in `.task-id` (keeping the drafting branch in `spec_branch`). The spec is drafted on one
branch and implemented on another, and task resolution matches either: without this every later
`crew` command in the worktree resolves no task and silently skips its gates. The checkout is
recorded as `.task-id` `worktree` only when it holds the recorded branch.

## The stage cost line

Under Claude Code the `agent_end` entries make the stage's cost line, so `tokens_reported=unknown` is
enough. Elsewhere tokens exist only in the harness, so record what it reported when the workers finish:

```bash
~/.agent/bin/crew-tool.py task-log "$TASK_DIR" --metric stage_end stage=implement workers=<n> tokens_reported=<n|unknown>
```

It validates the keys, appends the line to PROGRESS.md and prints `implement: 3 workers, 410k tokens`;
show that line in the handoff. Use `unknown` when the harness gives nothing, never an estimate.
`crew ls --cost` lists the lines of every task. Review's counterpart is in
`~/.cursor/agents/references/stage-rules.md`.
