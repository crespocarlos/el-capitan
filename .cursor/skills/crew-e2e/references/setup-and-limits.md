# crew e2e setup (one-time machine setup)

Offer a step only when `doctor` reports the matching check failing (step 4 matches a `notes` entry,
since `doctor` never fails on those), and run them one at a time, each after explicit confirmation.
This changes the user's machine, so it is never automatic.

0. **No usable worktree** (Step 2 returned none, or none without the guard risk). Ask for a local path
   to dedicate — an existing Kibana checkout the user is not using for day-to-day dev, or a new `git
   clone`/`git worktree add` the user confirms. After confirmation, add it under `kibana.worktrees` in
   `config.local.json` — never `config.json` — with a `label` and a port that does not collide with
   5601 or an existing entry. Re-run `worktrees` to confirm it appears, and check `doctor`'s
   `ports_free` note to confirm the chosen port is free before the first deploy.
1. **Missing or unrecognized repo.** For a failing `location` check, `gh repo clone
   elastic/nightshift-pr-helper <path>` with the path from that check. Confirm first: it writes a
   checkout. For a failing `repo` check, run the `git remote add` command from its `fix` line.
2. **`node_modules` missing.** `npm install` in the checkout.
3. **Server unreachable.** Either `npm run dev` (this session only, foreground) or `npm run
   launchd:install` (always on, builds first). Ask which; do not choose for the user, because one
   leaves a process behind and the other does not.
4. **Stale build or dangling LaunchAgent** (the `build_fresh` and `launchd` notes). `npm run
   launchd:restart-web` only when `launchd` says loaded; `npm run launchd:install` when the pinned
   `node` is gone after an nvm switch, or the agent is not loaded and the user wants it always on.
5. **`agent_cli` failing.** The harness nightshift runs is not installed or not signed in. Offer a
   `config.local.json` override only if another harness is installed, then re-run `doctor`.
6. **Outdated dev stack script** (the `dev_stack_eis` note). The installed `kibana.devStackScript` is
   the user's copy of `examples/kibana-dev-tools/dev_stack.sh` in the nightshift checkout; the example
   is documentation and is never run from there. An older copy ignores `DEV_STACK_EIS`, so a deploy
   can start a stack with no LLM connector. **Not a plain file replacement** — the installed script
   can carry working local edits the example lacks:
   a. Check whether the nightshift checkout is stale first: if `helper_up_to_date` is failing, say so
      and offer `git pull` there, since the example may already be fixed upstream.
   b. Compare capabilities, not just the `DEV_STACK_EIS` string: `grep -n
      'kibana.dev-stack.yml\|DEV_STACK_EIS' <installed> <example>`, and name any capability one has
      that the other lacks before proposing anything.
   c. Show a short, feature-level diff — `diff <installed> <example> | grep -E
      '^[<>].*\$\{?[A-Z_]+|^[<>].*(DEV_STACK|kibana\.dev)'` — not the full ~600-line diff, so the
      user judges the behavior change rather than scrolling boilerplate.
   d. After explicit confirmation, copy the installed script to a timestamped `.bak` beside it, verify
      the backup exists and is non-empty (stop if it does not), then copy the example over it.
   e. **Test before calling it done**: `bash -n <installed>` catches a copy syntax error, and run a
      dry-run or `--help` flag when the script has one. There is no safe way to exercise a dev-stack
      script without starting a stack; say so rather than implying the syntax check proves more.
   f. The script needs the secrets named in its header (for example `DEV_STACK_SANDBOX_API_KEY`) in
      the environment; report which are unset by name, never by value, and mask matched secret
      patterns in any diff or script text.

Never edit `config.json` (shared, tracked). Step 0 is the only step that writes `kibana.worktrees`, and
only with explicit confirmation of path and port; steps 1–5 never touch it, and step 6 is the only
change to the dev-stack script. Re-run `doctor` at the end and report the result.

# Recovery playbook

- **Stuck deploy** (`waiting-deploy` not advancing, per Step 4's stale check): `crew e2e stop`, then
  `crew e2e teardown` for that worktree if `worktrees` still shows `kibanaRunning: true`, then retry
  `start`. Do not retry `start` on top of a stack that never came down — that produces the next silent
  `waiting-deploy`.
- **Stale stack from an interrupted run**: the broader form of Step 4's leftover-stack check —
  `kibanaRunning: true` for that worktree with no run in progress for the key at all, not only after an
  explicit `stop`. `crew e2e teardown` before starting a new one.
- **Config clash** (`config_duplicate_keys`, or a `basePath`/public-URL mismatch hit manually): fix the
  duplicate or conflicting key in `config.local.json`; never edit `config.json`.
- **Port clash** (`ports_free`): identify what is listening (`lsof -i :5601`, `:9200`) before killing
  anything — it may be a stack you still need.

# Known limits

- Nightshift resolves only PRs it already tracks: review-requested PRs, test-plan subjects, or PRs with
  an earlier nightshift review. A PR you authored fails with `PR not found`; start it once from the
  nightshift UI (`/pr/<key>/e2e`) and the key is known from then on. Not a bug in crew.
- `~/worktrees/el-capitan-*` checkouts are not registered with nightshift. Runs use designated Kibana
  worktrees only — `kibana.worktrees` in nightshift's `config.local.json`. Setting one up (a checkout
  plus the config entry) is `crew e2e setup`'s job; this skill never creates the checkout or edits
  `config.json`.
- Some blockers appear only inside a run, so `doctor` cannot predict them: a dev stack with no LLM
  connector (`No connector available`), or a missing vault entry in nightshift's setup. Report them as
  environment limits with the exact error string; the fix belongs to the stack or nightshift, not to
  the PR or to crew.
- Per-run dev-stack setup is nightshift's own job: its runner calls `nightshift-setup.mjs` after each
  deploy, and the e2e agent re-runs it after a stack reset. Crew must not, or the two race.
- Teardown never restores the worktree's prior branch/HEAD/stash automatically: nightshift exposes no
  verified prior-ref field this tool can act on safely.
- `port_in_use` and the `ports_free` doctor note are a point-in-time TCP probe, not a lock: a port can
  free up or be taken between the check and the deploy.
