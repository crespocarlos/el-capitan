# Builder verification

`crew-builder` reads this right after anchoring to `WORK_DIR`, before the first task. The type-check
rule applies to every verify run and to Completion Protocol step 2; the two steps after it run before
the final reply and decide the report's `### Quality gates` section. Inputs: `TASK_DIR` and
`WORK_DIR`, as the builder received them.

## Type-check without emitting when `node_modules` is a symlink

When `test -L "$WORK_DIR/node_modules"` holds, emitting builds (`tsc -b`, or a repo script that builds
project references) write `.d.ts` files into the main repo through the symlink. Run `tsc --noEmit -p
<nearest tsconfig>` instead. If no no-emit form exists for the repo, record the type-check as
skipped with that reason — never skip silently.

Oversized command transcripts (Completion Protocol) go under `$TASK_DIR/artifacts/`.

## Verification run

Run `~/.agent/bin/crew-verify.py --repo <WORK_DIR> --task-dir $TASK_DIR` (for
a long run add `--background`, then `--wait $TASK_DIR/gates.json`). It runs the base branch's CI
(`src/crew/TOOLS.md` "Gates and cost"), prints `<name> exit=<N>` lines and writes
`$TASK_DIR/gates.json`. Never claim a result from memory or from a narrower command.

## Check the report in the same worker

Before replying, pipe the draft through
`~/.agent/bin/crew-verify.py report-check - --gates $TASK_DIR/gates.json` (a quoted heredoc on
stdin). On a mismatch, correct the report to match `gates.json` and run it once more; a second
failure goes in `### Errors` and the task is marked failed. It is not a new stage. A report that
still fails is saved anyway, with a WARN line in PROGRESS.md.
