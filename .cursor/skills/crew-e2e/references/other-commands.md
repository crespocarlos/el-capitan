# Other commands

The `crew e2e` verbs besides `start` and `status`, each mapped to its `crew-nightshift-e2e.py`
subcommand. Input: `TASK_DIR` (the active task, empty for none).

- `crew e2e ask "<text>"` → `followup <key> "<text>"`. Continues an existing session; needs a finished
  run and a still-deployed worktree, and nightshift errors clearly when neither holds.
- `crew e2e stop` → `stop <key>`. Confirm first: it kills a run in progress and its work is lost.
- `crew e2e teardown` → `stack-stop --worktree <id>`. Stops the Kibana/ES stack nightshift started
  there after a run; it does not stop the run, revert the checkout, or stop the nightshift web server.
  Confirm first, naming the worktree, its port, and whether Kibana is running, because a designated
  worktree can be the user's own dev checkout (`mainRepoRisk`, port 5601). Never offer `restore`. To
  stop nightshift's own server, tell the user: Ctrl-C the `npm run dev` terminal, or `npm run
  launchd:uninstall` for the LaunchAgent; this skill does neither.

  **Before and after.** If `$TASK_DIR/e2e-state.json` exists from Step 2, read the worktree's current
  state the same way and print both. Never restore automatically: nightshift exposes no verified
  previous ref, so show the diff and let the user decide. A stash count that grew means something was
  stashed during the run; say so.
