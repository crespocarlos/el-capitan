---
disable-model-invocation: true
name: crew-e2e
description: "Start and read a nightshift e2e run for a PR on demand: real browser/API tests of a deployed Kibana PR. Trigger: 'crew e2e PR #X', 'crew e2e <URL>', 'crew e2e' (current branch), 'crew e2e status', 'crew e2e ask \"<text>\"', 'crew e2e stop', 'crew e2e teardown', 'crew e2e setup'."
---

**Workflow**: build | **Stage**: test (on demand)

# On-demand e2e runs

Drives nightshift-pr-helper's e2e runner through its existing HTTP API. This is the one part of the
toolchain with no generic equivalent: it deploys a PR into a Kibana worktree, drives a real browser,
and writes a report. There is nothing to reimplement, only to call.

## Execution model

A run takes roughly 30 minutes and lives in nightshift's own process, so this skill **starts and
returns**. Never block waiting for a report; `crew e2e status` is a separate invocation. Nothing polls
unless the user opts in (Step 3), so say that in the start message instead of waiting to be asked.

## Step 0: preflight (always first)

```bash
python3 ~/.agent/bin/nightshift-e2e.py doctor
```

Exit 0 means every blocking check passed. Exit 1 means stop here and print the failing check's `fix`
verbatim — do not attempt the fix. `notes` may report a stale build or a missing LaunchAgent while
the server still works (`npm run dev`). Keep them:
- `build_fresh` appears only when the LaunchAgent is loaded (a `npm run dev` server never reads the
  build). When it says the build is older than HEAD, offer `npm run launchd:restart-web` (setup step
  4) before `start`. Never offer the restart when `launchd` says not loaded: it fails with `Could not
  find service`.
- `dev_stack_eis` means the installed `dev_stack.sh` ignores `DEV_STACK_EIS`, which nightshift sets
  on every deploy because a stack without EIS has no LLM connector and the run ends `blocked`. Offer
  setup step 6 before `start`, and say why.
- Name any failing note as a first suspect if the run later ends `blocked`, outdated, or much faster
  than the ~30 minutes expected.

On exit 3, or a `server unreachable` check, print the `fix` line and stop: `crew e2e setup` is the
guided path to a working machine.

## Step 1: resolve the PR

Accept `PR #123`, a GitHub URL, or nothing (current branch):

```bash
gh pr view ${1:+"$1"} --json number,headRefName,headRefOid,url,title,state,isDraft
gh repo view --json nameWithOwner
```

Build nightshift's key as `<owner>__<repo>__<number>` with `/` replaced by `__` in the repo part:
`elastic/kibana` + `12345` becomes `elastic__kibana__12345`. Pass it to every later command.

Refuse anything but `elastic/kibana` or `elastic/sandbox-service`. Nightshift reports the rejection
itself, but naming the limit here saves a round trip.

## Step 2: pick the worktree

```bash
python3 ~/.agent/bin/nightshift-e2e.py worktrees
```

Each entry has an `id`, a `label`, a `branch`, and whether Kibana is running. If the user named one,
use it. If exactly one exists, use it and say which. Otherwise ask, listing `label` and `branch`.

`--deploy` replaces whatever is deployed in that worktree, which is why it is never implied. The PR
counts as already deployed only when the worktree's `branch` equals the PR's `headRefName` **and**
`kibanaRunning` is true; then start without `--deploy`. Otherwise (a matching branch with Kibana not
running is not deployed, and a `null` branch is unknown, so not deployed), ask. Never start without
`--deploy` first to see whether it works: a start that nightshift rejects as not deployed costs a
round trip and a second confirmation.

Ask every open question in one structured form (the harness's multiple-choice question tool, with
one question per decision), never as prose that a single "yes" can answer ambiguously:
- **Worktree**, only when several exist.
- **Deploy**, only when not already deployed: `--deploy` (replaces what is deployed there) or cancel.
- **Doctor notes that apply** (`build_fresh` older than HEAD, `dev_stack_eis`): fix first, or continue.
- **Watch the run**: poll every 5 minutes up to 30 minutes (recommended), or no polling.
- **Focus** for `--instructions`, as optional free text.

Mark the recommended option first. Without a question tool, ask the same questions as a numbered
list and require an answer per number.

## Step 3: start

```bash
python3 ~/.agent/bin/nightshift-e2e.py start <key> --worktree <id> [--deploy] [--instructions "<focus>"]
```

Report the run page by copying the `run` field of the output exactly (never retype or rebuild the
URL), and stop. Do not queue and do not post: `POST /api/e2e/queue` posts a PR comment by default
(`e2e.queuePost`), which is external state the user has not asked for. A direct start reaches the same
runner.

If the user chose to watch the run, poll through the harness's loop or schedule feature: `status`
every 5 minutes, at most 30 minutes, stop on `done` or `failed`, then run Step 4 once. State that
nothing else runs in the background. Otherwise end with one line: nothing is polling the run; run
`crew e2e status` in about 30 minutes. The poll never stops the stack or the run.

## Step 4: read the result (`crew e2e status`)

```bash
python3 ~/.agent/bin/nightshift-e2e.py status <key>
python3 ~/.agent/bin/nightshift-e2e.py report <key>
```

`status` gives `state` (`waiting-deploy`, `running`, `done`, `failed`), whether the tested head is
now `outdated`, the `testedHead` SHA, and the run page. While `state` is `waiting-deploy` or
`running`, report that and stop.

Compare `testedHead` with the `headRefOid` from Step 1 yourself, not only nightshift's `outdated`
flag. On a mismatch, open with `report is for <testedHead7>, the PR is at <headRefOid7>; rerun` and
treat the contents as history, not a result for the PR.

Once `done`, `report` returns the verdict, summary, `prIntent`, `approach`, `setup`, `checks` (each
with `status`, `via` list, `category`, `details`, `evidence`, `screenshots` and a computed
`end_to_end`), `findings`, `environmentChanges`, `notCovered`, and `not_end_to_end`: passing checks
observed only through a health probe, a unit command, or a script. A check is end-to-end only when it
was not skipped and observed through `ui`, `api`, `es` or `log`. Quote `not_end_to_end` explicitly: a
green run whose checks were mostly `unit` or `health` is not end-to-end evidence, and reporting it as
if it were is the one misleading outcome this skill can produce.

Render the report in chat, then write the same text to `E2E.md`. Build it from the JSON only; do not
retell it from memory.

```markdown
## E2E: <title> (#<number>) — <verdict>
<summary>
Tested head `<testedHead7>`; PR at `<headRefOid7>`. Approach: <approach>. Run: <run field>

### Checks (<end-to-end count> of <total> end-to-end)
| Check | Status | Observed via | Category |
|---|---|---|---|
| <title> | pass/fail/warn/skipped | ui, api | feature |

### Findings
- **bug** — <title>: <detail, one line>        (group by kind: bug, concern, note, positive)

### Not end-to-end
<not_end_to_end titles, or "none">

### Left in the environment
<environmentChanges, one bullet each; include injected faults and debug lines and whether reverted>

### Not covered
<notCovered>
```

Show at most a 300-character excerpt of any `evidence`, point to the run page for screenshots, and
never paste credentials or tokens that appear in evidence.

A `blocked` verdict is not a result for the PR. State the blocking cause from the summary or findings
in one line (for example an environment limit such as a missing connector), say that the PR's behavior
is unverified, and list passed checks only as "environment checks that passed", never as evidence for
the PR. Then give the next step: which prerequisite to fix, or `crew e2e setup` when `doctor` notes
point at it. Do not offer a rerun until the cause is addressed. Name the `doctor` notes as suspects
(Step 0).

Write the report to `$TASK_DIR/E2E.md` when a source `~/.agent/bin/task-env.sh` resolves a task,
otherwise to `/tmp/crew-e2e-<key>/E2E.md`. Prefix the rendered report with the date.

## Other commands

- `crew e2e ask "<text>"` → `followup <key> "<text>"`. Continue an existing session; requires a
  finished run and a still-deployed worktree, and nightshift errors clearly when neither holds.
- `crew e2e stop` → `stop <key>`. Confirm first: it kills a run in progress and its work is lost.
- `crew e2e teardown` → `stack-stop --worktree <id>`. Stops the Kibana/ES stack nightshift started
  in that worktree after a run; it does not stop the run, revert the checkout, or stop the nightshift
  web server. Confirm first, naming the worktree, its port and whether Kibana is running, because a
  designated worktree can be the user's own dev checkout (index 0, port 5601). Never offer `restore`.
  To stop nightshift's own server, tell the user: Ctrl-C the `npm run dev` terminal, or `npm run
  launchd:uninstall` for the LaunchAgent; this skill does neither.

## crew e2e setup (one-time machine setup)

Offer a step only when `doctor` reports the matching check failing (step 4 matches a `notes` entry,
since `doctor` never fails on those), and run them one at a time, each after explicit confirmation.
This changes the user's machine, so it is never automatic.

1. **Missing or unrecognized repo.** For a failing `location` check, `gh repo clone
   elastic/nightshift-pr-helper <path>` — the path from that check. Confirm first: it writes a
   checkout. For a failing `repo` check, run the `git remote add` command from its `fix` line.
2. **`node_modules` missing.** `npm install` in the checkout.
3. **Server unreachable.** Either `npm run dev` (this session only, foreground) or
   `npm run launchd:install` (always on, builds first). Ask which; do not choose for the user, because
   one leaves a process behind and the other does not.
4. **Stale build or dangling LaunchAgent** (the `build_fresh` and `launchd` notes).
   `npm run launchd:restart-web` only when `launchd` says loaded; `npm run launchd:install` when the
   pinned `node` is gone (after an nvm switch) or the agent is not loaded and the user wants it
   always on.
5. **`agent_cli` failing.** The harness nightshift is configured to run is not installed or not signed
   in. Offer a `config.local.json` override only if another harness is installed, then re-run `doctor`.

6. **Outdated dev stack script** (the `dev_stack_eis` note). The installed `kibana.devStackScript` is
   the user's copy of `examples/kibana-dev-tools/dev_stack.sh` in the nightshift checkout; the example
   is documentation and is never run from there. An older copy ignores `DEV_STACK_EIS`, so a deploy
   can start a stack with no LLM connector. Show `diff <installed> <example>` first, because the user
   may have local edits. After explicit confirmation, copy the installed script to a timestamped
   `.bak` beside it, verify the backup exists and is non-empty, then copy the example over it. The
   script needs the secrets named in its header (for example `DEV_STACK_SANDBOX_API_KEY`) in the
   user's environment; report which are unset by name, never by value.

Never edit `config.json` (shared, tracked) and never touch `kibana.worktrees` here. Those describe
the user's environment, not nightshift's health. Step 6 is the only change to the dev-stack script. Re-run `doctor` at the end and
report the result.

## Known limits

- Nightshift resolves only PRs it already tracks: review-requested PRs, test-plan subjects, or PRs with
  an earlier nightshift review. A PR you authored fails with `PR not found`; start it once from the
  nightshift UI (`/pr/<key>/e2e`) and the key is known from then on. Do not treat that as a bug in crew.
- `~/worktrees/el-capitan-*` checkouts are not registered with nightshift. Runs use designated Kibana
  worktrees only.
- Some blockers appear only inside a run, so `doctor` cannot predict them: a dev stack with no LLM
  connector (`No connector available`), or a missing vault entry in nightshift's setup. Report them as
  environment limits with the exact error string; the fix belongs to the stack or nightshift's setup,
  not to the PR or to crew.
- Per-run dev-stack setup is nightshift's own job: its runner calls `nightshift-setup.mjs` after each
  deploy and the e2e agent re-runs it after a stack reset. Crew must not, or the two race.
