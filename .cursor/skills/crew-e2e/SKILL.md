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
python3 ~/.agent/bin/crew-nightshift-e2e.py doctor
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
- `ports_free` flags a listener already on 5601 or 9200 (ES/Kibana's defaults) — a likely clash with
  the worktree you are about to deploy into, not a hard stop. Name it when choosing a worktree in
  Step 2, especially if a run goes `blocked` right after a deploy.
- `config_duplicate_keys` means a hand-edited `config.local.json` has a repeated key; JSON parsing
  silently keeps only the last occurrence, so the duplicate is invisible until this check names it.
  Fix it before Step 2 if the symptom is nightshift behaving as if an edit you made was never applied.
- `helper_up_to_date` means the nightshift checkout is behind its remote. It skips (reports `ok`)
  whenever it cannot reach the remote or compute the distance — never block on it, only mention it.

If the PR's changed files include `instructions/*.md.text`, an agent definition, or another
prompt/instruction file, and `agent_cli` in `doctor` names a harness with no reasoning/LLM connector
configured, say so before starting: cap the expected verdict at `partial` and name which behavior
(the prompt or agent's actual reasoning) cannot be exercised. Running the full ~30 minutes to learn
that only at the end wastes the run.

On exit 3, or a `server unreachable` check, print the `fix` line and stop: `crew e2e setup` is the
guided path to a working machine.

**Secret hygiene (applies to every step below).** Before showing script or config text in chat —
`diff` output, `config.local.json` contents, environment variable listings — mask any value matching
a credential shape (API keys, tokens, anything after `=` in a line naming `KEY`, `SECRET`, `TOKEN`,
or `PASSWORD`) with `***`. Never paste an unmasked value, even partially, even from a local file.

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

If `gh pr view` succeeds but you cannot confirm the PR is one nightshift tracks (review-requested,
a test-plan subject, or previously reviewed — see Known limits), say so now with the exact UI link
to start it there first: `<nightshift base URL>/pr/<key>/e2e`. Do not wait for `start` to fail with
`PR not found` before mentioning this; it is the single most common Step-3 failure and the fix is
always the same link.

## Step 2: pick the worktree

```bash
python3 ~/.agent/bin/crew-nightshift-e2e.py worktrees
```

Each entry has an `id`, a `label`, a `branch`, `kibanaPort`, `kibanaRunning`, `path` (when nightshift
reports it), `dirty` (uncommitted paths in that worktree, `[]` when clean), `dirtyCount`, and
`mainRepoRisk` — true when `kibanaPort` is 5601, the documented convention for the user's own dev
checkout rather than a dedicated e2e worktree (see Known limits).

**Worktree guard.** Before offering `--deploy` on a worktree:
- If `mainRepoRisk` is true, or `dirtyCount` is nonzero, do not default to it even if it is the only
  one returned. Name the risk explicitly (port 5601 / N uncommitted files) and require the user to
  confirm that specific worktree before deploying into it.
- If no worktree carries that risk and exactly one exists, use it and say which.
- Otherwise ask, listing `label`, `branch`, and the risk flags for each.

If nothing comes back from `worktrees` and the user has no dedicated worktree set up at all, that is
a one-time setup gap, not a missing-argument error: say so and point at `crew e2e setup` to add one
(a `kibana.worktrees` entry in `config.local.json` and a prepared checkout) rather than deploying
into whatever was returned.

`--deploy` replaces whatever is deployed in that worktree, which is why it is never implied. The PR
counts as already deployed only when the worktree's `branch` equals the PR's `headRefName` **and**
`kibanaRunning` is true; then start without `--deploy`. Otherwise (a matching branch with Kibana not
running is not deployed, and a `null` branch is unknown, so not deployed), ask. Never start without
`--deploy` first to see whether it works: a start that nightshift rejects as not deployed costs a
round trip and a second confirmation.

**Preview the deploy.** When asking to confirm `--deploy`, say what it does to that worktree before
the user answers: `git checkout --force --detach <headRefOid>`, removes untracked files, and clears
the rspack cache. This is a real reset of whatever is there now, not an incremental update.

**Record the starting state** before any `--deploy` (skip for a worktree you are not deploying into):

```bash
cd <worktree path> \
  && git rev-parse --abbrev-ref HEAD && git rev-parse HEAD && git status --porcelain \
  && git stash list | wc -l \
  && shasum -a 256 kibana.dev.yml 2>/dev/null || true
```

Write branch, HEAD SHA, the porcelain status, stash count, and the yaml hash to
`$TASK_DIR/e2e-state.json` (or `/tmp/crew-e2e-<key>/e2e-state.json` without a task). This is the
baseline Step 4's teardown prints a diff against — record it even if you expect to restore nothing.

**Auto-generate `--instructions`** instead of leaving it blank by default. Build one to two sentences
of focus from what is already available, and let the user edit it rather than write from scratch:
- The SPEC's acceptance criteria (`$TASK_DIR/SPEC.md`), if a task is active.
- The PR description (`gh pr view --json body`).
- A changed-file classification from Step 1's diff: server route/service, UI component, or
  prompt/agent file — each implies a different kind of check worth asking the tester to run.

Ask every open question in one structured form (the harness's multiple-choice question tool, with
one question per decision), never as prose that a single "yes" can answer ambiguously:
- **Worktree**, when several exist or the chosen one carries a guard risk (above).
- **Deploy**, only when not already deployed: `--deploy` (replaces what is deployed there, see
  preview above) or cancel.
- **Doctor notes that apply** (`build_fresh` older than HEAD, `dev_stack_eis`, `ports_free`): fix
  first, or continue.
- **Watch the run**: poll every 5 minutes up to 30 minutes (recommended), or no polling.
- **Focus** for `--instructions`, pre-filled with the auto-generated draft above, editable.

Mark the recommended option first. Without a question tool, ask the same questions as a numbered
list and require an answer per number.

## Step 3: start

```bash
python3 ~/.agent/bin/crew-nightshift-e2e.py start <key> --worktree <id> [--deploy] [--instructions "<focus>"]
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
python3 ~/.agent/bin/crew-nightshift-e2e.py status <key> [--worktree-path <path from Step 2>]
python3 ~/.agent/bin/crew-nightshift-e2e.py report <key>
```

`status` gives `state` (`waiting-deploy`, `running`, `done`, `failed`), whether the tested head is
now `outdated`, the `testedHead` SHA, and the run page. With `--worktree-path` and `state: failed`,
it also returns `fatal`: the dev-stack log's last `FATAL` line, which is usually the real cause —
nightshift's own `error` field is often an earlier, misleading symptom (for example a missing build
artifact logged well before the actual failure). Report `fatal` when present instead of, or in
addition to, `error`.

**Stale runs.** `waiting-deploy` with no change across two consecutive polls (10+ minutes with no
state transition) is stuck, not merely slow: report it as stale rather than polling silently to the
30-minute cap, and suggest `crew e2e stop` followed by a fresh `start`. The same applies if `stop`
was already run but Kibana is still reported `kibanaRunning: true` in `worktrees` — offer `crew e2e
teardown` for that worktree before a retry, since a leftover stack from a killed run can make the
next `start` sit in `waiting-deploy` indefinitely.

While `state` is `waiting-deploy` or `running` (and not stale), report that and stop.

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

### Coverage of the PR surface
<each changed file from Step 1's diff, mapped to the check(s) that touched it (by title match or
evidence path); files with no matching check listed under "no check touched this file">
```

Build the coverage section from the PR's changed-file list (Step 1) against each check's `title`,
`category`, and `evidence`; it answers "what in the diff did nothing observe" directly, which
`not_end_to_end` does not (`not_end_to_end` is about *how* a check that ran observed things, not
about which files were never touched by any check).

Show at most a 300-character excerpt of any `evidence`, point to the run page for screenshots, and
never paste credentials or tokens that appear in evidence (see Secret hygiene, Step 0).

A `blocked` verdict is not a result for the PR. State the blocking cause from the summary or findings
in one line (for example an environment limit such as a missing connector), say that the PR's behavior
is unverified, and list passed checks only as "environment checks that passed", never as evidence for
the PR. Then give the next step: which prerequisite to fix, or `crew e2e setup` when `doctor` notes
point at it. Do not offer a rerun until the cause is addressed. Name the `doctor` notes as suspects
(Step 0).

Write the report to `$TASK_DIR/E2E.md` when a source `~/.agent/bin/task-env.sh` resolves a task,
otherwise to `/tmp/crew-e2e-<key>/E2E.md`. Prefix the rendered report with the date.

**Keep a history.** Nightshift replaces the run directory for a PR key on its next run, so a report
you cite can be gone by the time anyone rereads this conversation. As soon as a run finishes, copy
the rendered report, the raw `report` JSON, and `testedHead` into
`$TASK_DIR/e2e/<testedHead7>/` (or `/tmp/crew-e2e-<key>/e2e/<testedHead7>/` without a task) before
reporting the summary — this is the durable copy, not nightshift's run directory.

## Other commands

- `crew e2e ask "<text>"` → `followup <key> "<text>"`. Continue an existing session; requires a
  finished run and a still-deployed worktree, and nightshift errors clearly when neither holds.
- `crew e2e stop` → `stop <key>`. Confirm first: it kills a run in progress and its work is lost.
- `crew e2e teardown` → `stack-stop --worktree <id>`. Stops the Kibana/ES stack nightshift started
  in that worktree after a run; it does not stop the run, revert the checkout, or stop the nightshift
  web server. Confirm first, naming the worktree, its port and whether Kibana is running, because a
  designated worktree can be the user's own dev checkout (`mainRepoRisk` from Step 2, port 5601).
  Never offer `restore`. To stop nightshift's own server, tell the user: Ctrl-C the `npm run dev`
  terminal, or `npm run launchd:uninstall` for the LaunchAgent; this skill does neither.

  **Before and after.** If `$TASK_DIR/e2e-state.json` exists from Step 2, read the worktree's current
  branch/HEAD/dirty state the same way it was recorded, and print both: the state before the deploy
  and the state now. Never restore automatically — nightshift does not expose a verified "previous
  ref" for this tool to act on, so the only safe move is to show the diff and let the user decide
  (`git checkout <recorded branch>`, `git reset --hard <recorded HEAD>`, or leave it). Treat a stash
  count that grew as a signal something was stashed during the run and say so explicitly.

## crew e2e setup (one-time machine setup)

Offer a step only when `doctor` reports the matching check failing (step 4 matches a `notes` entry,
since `doctor` never fails on those), and run them one at a time, each after explicit confirmation.
This changes the user's machine, so it is never automatic.

0. **No usable worktree** (Step 2 returned none, or none without the guard risk). Ask for a local
   path to dedicate (an existing Kibana checkout the user is not using for day-to-day dev, or a new
   `git clone`/`git worktree add` the user confirms). After confirmation, add it under
   `kibana.worktrees` in `config.local.json` — never `config.json` — with a `label` and a port that
   does not collide with 5601 or an existing entry. Re-run `worktrees` to confirm it appears, and
   `doctor`'s `ports_free` note to confirm the chosen port is free before the first deploy.
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
   can start a stack with no LLM connector. **Do not treat this as a plain file replacement** — the
   installed script can carry working local edits the example does not have:
   a. First check whether the nightshift checkout itself is stale: if `doctor`'s `helper_up_to_date`
      note is failing, say so and offer `git pull` there first, since the example may already be
      fixed upstream.
   b. Compare capabilities, not just the `DEV_STACK_EIS` string: `grep -n
      'kibana.dev-stack.yml\|DEV_STACK_EIS' <installed> <example>` and name any capability the
      installed script has that the example lacks, or vice versa, before proposing anything.
   c. Show a short, feature-level diff — `diff <installed> <example> | grep -E '^[<>].*\$\{?[A-Z_]+|^[<>].*(DEV_STACK|kibana\.dev)'` or similar, not the full ~600-line diff — so the user can
      judge the actual behavior change, not scroll past boilerplate.
   d. After explicit confirmation, copy the installed script to a timestamped `.bak` beside it,
      verify the backup exists and is non-empty (stop here if it does not), then copy the example
      over it.
   e. **Test before calling it done**: run `bash -n <installed>` to catch a syntax error from the
      copy, and if a dry-run or `--help` flag exists in the script, run that too. There is no safe
      way to fully exercise a dev-stack script without actually starting a stack; say so rather than
      implying the syntax check proves more than it does.
   f. The script needs the secrets named in its header (for example `DEV_STACK_SANDBOX_API_KEY`) in
      the user's environment; report which are unset by name, never by value (Secret hygiene, Step
      0) — and never print the diff or script contents without masking matched secret patterns.

Never edit `config.json` (shared, tracked). Step 0 is the only step that writes `kibana.worktrees`,
and only with explicit confirmation of the path and port; steps 1–5 never touch it, and step 6 is the
only change to the dev-stack script. Re-run `doctor` at the end and report the result.

## Recovery playbook

- **Stuck deploy** (`waiting-deploy` not advancing, per Step 4's stale check): `crew e2e stop`, then
  `crew e2e teardown` for that worktree if `worktrees` still shows `kibanaRunning: true`, then retry
  `start`. Do not retry `start` on top of a stack that never fully came down — that is what produces
  the next silent `waiting-deploy`.
- **Stale stack from an earlier, interrupted run**: the broader form of Step 4's leftover-stack
  check — `worktrees` shows `kibanaRunning: true` for that worktree with no run in progress for the
  key at all (not only after an explicit `stop`, which is Step 4's narrower case). `crew e2e
  teardown` for that worktree before starting a new one.
- **Config clash** (`config_duplicate_keys`, or a `basePath`/public-URL mismatch you hit manually):
  fix the duplicate or conflicting key in `config.local.json` directly; never edit `config.json`
  (shared, tracked).
- **Port clash** (`ports_free`): identify what is listening (`lsof -i :5601`, `:9200`) before killing
  anything — it may be a stack you still need.

## Known limits

- Nightshift resolves only PRs it already tracks: review-requested PRs, test-plan subjects, or PRs with
  an earlier nightshift review. A PR you authored fails with `PR not found`; start it once from the
  nightshift UI (`/pr/<key>/e2e`) and the key is known from then on. Do not treat that as a bug in crew.
- `~/worktrees/el-capitan-*` checkouts are not registered with nightshift. Runs use designated Kibana
  worktrees only — `kibana.worktrees` in nightshift's `config.local.json`. Setting one up (a checkout
  plus the config entry) is `crew e2e setup`'s job when `worktrees` returns none usable; this skill
  does not create the checkout or edit `config.json` itself.
- Some blockers appear only inside a run, so `doctor` cannot predict them: a dev stack with no LLM
  connector (`No connector available`), or a missing vault entry in nightshift's setup. Report them as
  environment limits with the exact error string; the fix belongs to the stack or nightshift's setup,
  not to the PR or to crew.
- Per-run dev-stack setup is nightshift's own job: its runner calls `nightshift-setup.mjs` after each
  deploy and the e2e agent re-runs it after a stack reset. Crew must not, or the two race.
- Teardown never restores the worktree's prior branch/HEAD/stash automatically (see "Before and
  after" above): nightshift does not expose a verified prior-ref field this tool can act on safely.
- `port_in_use` and the `ports_free` doctor note are a point-in-time TCP probe, not a lock: a port can
  free up or get taken between the check and the actual deploy.
