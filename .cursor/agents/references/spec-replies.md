# Spec subagent replies

`crew-specwriter` reads this before its first dispatch. Inputs: `TASK_DIR`, the spec's task directory,
and `SPEC_RUN`, the run directory `crew-task.py prepare-spec` created under `$TASK_DIR/spec-agents/`.

Every `specwriter-*` dispatch prompt opens with two lines, so the subagent-stop hook (Claude Code and
Cursor) can tell these agents from any other subagent and save each reply where the spec writer reads
it; a subagent that merely quotes a marker saves nothing, because no `.expect` holds its nonce. The
explorer prompt `prepare-spec` wrote has both; a critic's are:

1. Line one is what `~/.agent/bin/crew-review-findings.py expect --review-dir "$SPEC_RUN" --persona
   <agent>` prints, run just before that dispatch; `<agent>` is the full name, such as
   `specwriter-scope`.
2. Line two is `crew-task: <TASK_DIR>`, so the hook records the run's usage on the task.

Read each reply from `$SPEC_RUN/<agent>.out.md`. The latest reply to a marker is the reply: a
resumed agent's lands there and the earlier one moves to `<agent>.prev.md`, so its `Verdict:` line is
the critic's outcome. A reply is pending, not answered, while `<agent>.unanswered` sits beside it (an
empty reply, a pointer, a critic with no `Verdict:` line): resume it under the no-reply rule of
[dispatch](dispatch.md). Only when `<agent>.out.md` is missing after the agent stops did the hook
save nothing: take the reply the harness returned and pipe it, unedited, into
`~/.agent/bin/crew-review-findings.py save-out --review-dir "$SPEC_RUN" --persona <agent> --harness
<name>`.
