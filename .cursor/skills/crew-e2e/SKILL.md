---
disable-model-invocation: true
name: crew-e2e
description: "Start and read a nightshift e2e run for a PR on demand: real browser/API tests of a deployed Kibana PR. Trigger: 'crew e2e PR #X', 'crew e2e <URL>', 'crew e2e' (current branch), 'crew e2e status', 'crew e2e ask \"<text>\"', 'crew e2e stop', 'crew e2e teardown', 'crew e2e setup'."
---

**Workflow**: build | **Stage**: test (on demand)

# On-demand e2e runs

Drives nightshift-pr-helper's e2e runner through its HTTP API — the one part of the toolchain with no
generic equivalent: it deploys a PR into a Kibana worktree, drives a real browser, and writes a
report. There is nothing to reimplement, only to call.

## Execution model

A run takes roughly 30 minutes and lives in nightshift's own process, so this skill **starts and
returns**. Never block waiting for a report; `crew e2e status` is a separate invocation. Nothing polls
unless the user opts in (Step 3) — say that in the start message instead of waiting to be asked.
`TASK_DIR` is the active task (`crew-tool.py task-context --field task_dir`), empty without one.

## Step 0: preflight (always first)

```bash
~/.agent/bin/crew-nightshift-e2e.py doctor
```

Exit 0 means every blocking check passed. Exit 1 means stop and print the failing check's `fix`
verbatim — do not attempt the fix. On exit 3, or a `server unreachable` check, print the `fix` line and
stop: `crew e2e setup` is the guided path to a working machine.

`notes` may report a stale build or a missing LaunchAgent while the server still works. Keep them:
- `build_fresh` appears only when the LaunchAgent is loaded (an `npm run dev` server never reads the
  build). When the build is older than HEAD, offer `npm run launchd:restart-web` before `start`. Never
  offer the restart when `launchd` says not loaded: it fails with `Could not find service`.
- `dev_stack_eis` means the installed `dev_stack.sh` ignores `DEV_STACK_EIS`, which nightshift sets on
  every deploy because a stack without EIS has no LLM connector and the run ends `blocked`. Offer
  setup step 6 before `start`, and say why.
- `ports_free` flags a listener already on 5601 or 9200 (ES/Kibana's defaults) — a likely clash with
  the worktree you are about to deploy into, not a hard stop. Name it when choosing a worktree.
- `config_duplicate_keys` means a hand-edited `config.local.json` repeats a key; JSON parsing silently
  keeps the last one, so the duplicate is invisible until this check names it.
- `helper_up_to_date` means the nightshift checkout is behind its remote. It reports `ok` whenever it
  cannot reach the remote or compute the distance — never block on it, only mention it.

Name any failing note as a first suspect if the run later ends `blocked`, outdated, or much faster
than the expected ~30 minutes.

If the PR's changed files include `instructions/*.md.text`, an agent definition, or another
prompt/instruction file, and `agent_cli` names a harness with no reasoning/LLM connector configured,
say so before starting: cap the expected verdict at `partial` and name which behavior (the prompt or
agent's actual reasoning) cannot be exercised.

**Secret hygiene (every step).** Before showing script or config text in chat — `diff` output,
`config.local.json` contents, environment listings — mask any value matching a credential shape (API
keys, tokens, anything after `=` in a line naming `KEY`, `SECRET`, `TOKEN`, or `PASSWORD`) with `***`.
Never paste an unmasked value, even partially, even from a local file.

## Step 1: resolve the PR

Take `PR #123` (passed as `--pr 123`), a URL, or nothing (current branch):

```bash
~/.agent/bin/crew-tool.py pr-read view --fields number,headRefName,headRefOid,url,title,state,isDraft
~/.agent/bin/crew-tool.py pr-read repo --fields nameWithOwner
```

Build nightshift's key as `<owner>__<repo>__<number>`, with `/` replaced by `__` in the repo part:
`elastic/kibana` + `12345` becomes `elastic__kibana__12345`. Pass it to every later command.

Refuse anything but `elastic/kibana` or `elastic/sandbox-service`. Nightshift reports the rejection
itself; naming the limit here saves a round trip.

If you cannot confirm nightshift tracks the PR (review-requested, a test-plan subject, or previously
reviewed — see [setup and limits](references/setup-and-limits.md#known-limits)), say so now with the
UI link to start it there first, `<nightshift base URL>/pr/<key>/e2e`, rather than waiting for
`start` to fail with `PR not found`.

## Step 2: pick the worktree

```bash
~/.agent/bin/crew-nightshift-e2e.py worktrees
```

Each entry has an `id`, `label`, `branch`, `kibanaPort`, `kibanaRunning`, `path`, `dirty` (uncommitted
paths, `[]` when clean), `dirtyCount`, and `mainRepoRisk` — true when `kibanaPort` is 5601, the
documented convention for the user's own dev checkout rather than a dedicated e2e worktree.

**Worktree guard.** Before offering `--deploy` on a worktree:
- If `mainRepoRisk` is true or `dirtyCount` is nonzero, do not default to it even when it is the only
  one returned. Name the risk explicitly (port 5601 / N uncommitted files) and require the user to
  confirm that specific worktree.
- If no worktree carries that risk and exactly one exists, use it and say which.
- Otherwise ask, listing `label`, `branch`, and the risk flags for each.

If `worktrees` returns nothing, that is a one-time setup gap, not a missing argument: point at
`crew e2e setup` rather than deploying into whatever came back.

`--deploy` replaces whatever is deployed in that worktree, so it is never implied. The PR counts as
deployed only when the worktree's `branch` equals the PR's `headRefName` **and** `kibanaRunning` is
true; then start without `--deploy`. Otherwise ask, rather than trying a start without `--deploy` (a
rejected start costs a round trip and a second confirmation). When asking, say what it does: `git
checkout --force --detach <headRefOid>`, removes untracked files, clears the rspack cache — a real
reset, not an incremental update.

**Record the starting state** before any `--deploy` (skip for a worktree you are not deploying into):

```bash
~/.agent/bin/crew-tool.py repo-facts --root <worktree path>
```

Write the branch, HEAD SHA, every dirty path, and the yaml hash to `$TASK_DIR/e2e-state.json` (or
`/tmp/crew-e2e-<key>/e2e-state.json` without a task). The stash count and yaml hash come from the
worktree: `git stash list | wc -l` and `shasum -a 256 kibana.dev.yml`. This is the
baseline Step 4's teardown prints a diff against — record it even when you expect to restore nothing.

**Auto-generate `--instructions`** rather than leaving it blank. Build one or two sentences of focus
from what is available, and let the user edit it rather than write from scratch:
- the SPEC's acceptance criteria (`$TASK_DIR/SPEC.md`), when a task is active;
- the PR description (`~/.agent/bin/crew-tool.py pr-read view --pr N --fields body`);
- a changed-file classification from Step 1's diff — server route/service, UI component, or
  prompt/agent file — each implying a different check worth asking the tester to run.

Ask every open question in one structured form (the harness's multiple-choice question tool, one per
decision), never as prose a single "yes" can answer ambiguously:
- **Worktree**, when several exist or the chosen one carries a guard risk.
- **Deploy**, only when not already deployed: `--deploy` (see the preview) or cancel.
- **Doctor notes that apply** (`build_fresh` older than HEAD, `dev_stack_eis`, `ports_free`): fix
  first, or continue.
- **Watch the run**: poll every 5 minutes up to 30 minutes (recommended), or no polling.
- **Focus** for `--instructions`, pre-filled with the generated draft, editable.

Mark the recommended option first. Without a question tool, ask the same questions as a numbered list
and require an answer per number.

## Step 3: start

```bash
~/.agent/bin/crew-nightshift-e2e.py start <key> --worktree <id> [--deploy] [--instructions "<focus>"]
```

Report the run page by copying the `run` field exactly (never retype or rebuild the URL), and stop. Do
not queue and do not post: `POST /api/e2e/queue` posts a PR comment by default (`e2e.queuePost`),
external state the user has not asked for. A direct start reaches the same runner.

If the user chose to watch, poll through the harness's loop or schedule feature: `status` every 5
minutes, at most 30 minutes, stop on `done` or `failed`, then run Step 4 once. State that nothing else
runs in the background. Otherwise end with one line: nothing is polling the run; run `crew e2e status`
in about 30 minutes. The poll never stops the stack or the run.

## Step 4: read the result (`crew e2e status`)

```bash
~/.agent/bin/crew-nightshift-e2e.py status <key> [--worktree-path <path from Step 2>]
~/.agent/bin/crew-nightshift-e2e.py report <key>
```

`status` gives `state` (`waiting-deploy`, `running`, `done`, `failed`), whether the tested head is now
`outdated`, the `testedHead` SHA, and the run page. With `--worktree-path` and `state: failed`, it also
returns `fatal`: the dev-stack log's last `FATAL` line, usually the real cause, since nightshift's own
`error` is often an earlier, misleading symptom. Report `fatal` when present, instead of or beside
`error`.

**Stale runs.** `waiting-deploy` unchanged across two consecutive polls (10+ minutes) is stuck: report
it as stale and suggest `crew e2e stop` then a fresh `start`. If `stop` already ran but `worktrees`
still reports `kibanaRunning: true`, offer `crew e2e teardown` first: a leftover stack keeps the next
`start` in `waiting-deploy`.

While `state` is `waiting-deploy` or `running` and not stale, report that and stop.

Compare `testedHead` with Step 1's `headRefOid` yourself, not only nightshift's `outdated` flag. On a
mismatch, open with `report is for <testedHead7>, the PR is at <headRefOid7>; rerun` and treat the
contents as history, not a result for the PR.

Render and persist the report per [report rendering](references/report-rendering.md).

## Other commands

`crew e2e ask`, `stop` and `teardown`: read [other commands](references/other-commands.md) first.

## crew e2e setup, recovery, and known limits

Follow [setup and limits](references/setup-and-limits.md) for machine setup, the recovery playbook, and
what nightshift cannot do.
