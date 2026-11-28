# Hooks

Every harness registration runs one command, `crew-hook.py <harness> <event>`: the harness's adapter
(`src/crew/harness/`) normalises the payload, the rules `.claude/hooks/contract.json` names for each canonical event
run from `~/.agent/hooks` (install's copy), and the adapter encodes the answer ([Harness adapters](#harness-adapters)). Each rule is
one small file under `.claude/hooks/`; read any of them before you install. Two of them are guards, one process each
per tool call: the shell guard and the file guard. The guards are a security boundary:
[SECURITY.md](../SECURITY.md) says what they protect and how to report a bypass.

| Canonical event (Claude Code / Cursor) | Trigger | What it does |
|---|---|---|
| `pre_shell` (`PreToolUse` / `beforeShellExecution`) | Bash | `guard/shell.sh`, the shell guard: one process that reads the payload once, normalises the command once and runs its rules (below, [Rules](#rules)). |
| `pre_write` (`PreToolUse` / `preToolUse`) | Write, Edit, MultiEdit; Cursor Write, Edit, Delete | `check-task-spec-owner.sh`, the file guard, with its rules in `lib/spec_guard.py` (below). |
| `prompt_submit` (`UserPromptSubmit`; none in Cursor) | Each turn | `mode-anchor.sh` prints the active task, status, branch, and task directory so a long session does not drift out of the pipeline. The line is computed once by `spec-status-reconcile.sh` and cached. |
| `post_tool` (`PostToolUse`, `PostToolUseFailure` / `postToolUse`, `postToolUseFailure`) | Bash, Write, Edit; Cursor every tool | Emits local JSON telemetry |
| `post_shell` (`PostToolUse` / `afterShellExecution`) | Bash | `record-pr.sh` records the PR a successful `gh pr create` printed on its task (`crew-task.py record-pr`). Only a command with a real `gh … pr create` segment counts (the `lib/hook.sh` normaliser; text in an `echo` or a string does not), and only when its output holds exactly one distinct PR URL; with several it records nothing and lists them. It asks `gh pr view` for the head branch and matches the task's repo (the base, or the fork the head owner names) and `branch`. The single open match wins over DONE and ABANDONED ones; an IMPLEMENTING match gains the PR and goes through `mark-done`, any other single match only gains the PR; several record nothing and print each `mark-done` command. A head branch that is only some task's `spec_branch` records nothing and names that task; no match at all, in a repo that already has tasks, becomes a minimal DONE task with no spec. Any other command ends in shell; the outcome is Claude's additional context. Session-start reconcile still catches PRs opened any other way. |
| `subagent_stop` (`SubagentStop` / `subagentStop`) | Subagent ends | `capture-reply.sh` saves a crew agent's reply (`crew-review-findings.py capture`) when a line of the dispatch prompt is the `crew-review-out: <dir> <name> <nonce>` marker that `crew-review-findings.py expect` printed: a reviewer persona or the probe (`<review dir>/<persona>.out.md`; a claim-check explorer in its own `<review dir>/claims/<n>/explorer.out.md`), or a crew-specwriter subagent (`specwriter-explorer`, `specwriter-scope`, `specwriter-adversarial`: `<TASK_DIR>/spec-agents/<run>/<name>.out.md`). The position is not the check, and neither is the agent id: the nonce is, so the reply is saved only when `<name>.expect` holds the same nonce; a non-crew subagent that quotes a marker saves nothing. `.expect` stays after a save and the record keeps the nonce as consumed. In Cursor the dispatch prompt is the payload's `task` field when it holds a marker or task line, else the transcript's first user line; the transcript is the first of the payload's `agent_transcript_path`, `<conversation>/subagents/<subagent_id or child_conversation_id>.jsonl` derived from `transcript_path`, `$CURSOR_TRANSCRIPT_PATH` or that path, and a scan of those `subagents/` folders for the `task` nonce, whose first user line carries the marker; one that exists with no user line yet is polled for up to 3 s (`review_transcript.py`). A Cursor stop that saves nothing logs one line with the payload's key names, `subagent_id`, whether `child_conversation_id` is present and each candidate path with `exists`, `bytes` and `lines`, never content. A Cursor `status` of `error` or `aborted` saves nothing and leaves the dispatch pending. The reply is the `SubagentHandback` message, else Claude Code's `last_assistant_message` (documented as the final response; the transcript may lag), else the transcript's last assistant text (Cursor's transcript: `role` lines, read alike), else a `completed` Cursor run's `summary`, recorded as `reply_from: summary` with `<name>.unanswered` always written, so the continue below or `save-out --from-transcript` recovers the real reply (`persist` lists it under `### Reviewers`). A transcript whose first user line fails the marker check (the parent's, say) is never read for the reply; it is opened only to report a `malformed transcript`. Each record's `source` is `hook`, `transcript` (`save-out --from-transcript`) or `manual` (`save-out` from stdin, listed under `### Reviewers`). The latest reply to a marker is the reply: a later, different stop with the same marker (a resume, whatever its agent id) becomes `<name>.out.md` and the earlier reply moves to `<name>.prev.md` with its record. The same stop again (Cursor fires `subagentStop` twice) changes nothing and logs `already saved`: no `.prev.md`, no second `agent_end` (`~/.agent/state/capture-seen.txt`, behind `capture-reply.lock`, waited on for at most 10 s, then `lock busy` and unlocked). A stop is recorded as seen only when it wrote something, so a repeat of a failed save retries. When the reply leaves `<name>.unanswered`, the hook asks the agent once per nonce to deliver, with the `deliver now` line of the dispatch rule: Cursor's `followup_message` on a `completed` first loop (the entry has `loop_limit: 1`), Claude Code's `{"decision": "block", "reason": ...}` unless `stop_hook_active` is set; `<name>.continued` records the nonce. An `.out.md` recorded for another nonce is a name collision and is kept. A reply that answers nothing (empty, `status: failed`, a pointer to an earlier turn with no finding, a critic with no `Verdict:` line, a final line still half-written so an earlier turn is read) leaves `<name>.unanswered` beside it, so the dispatch stays pending until a later reply answers. Each record names the harness (`claude-code` or `cursor`), the agent id (Cursor: `subagent_id`) and the model (Cursor: `subagent_model`, null when the payload has none). A transcript with no message line is skipped with a `malformed transcript` line. Every outcome line also goes to `~/.agent/state/capture-reply.log`; on Cursor's event stdout is `{}`, and Cursor's Claude-format copy never processes (the claude-code adapter drops it). The same hook appends an `agent_end` METRIC (with `agent_id`, so a resumed agent counts once, and `harness`) to the task a `crew-task: <TASK_DIR>` prompt line names, only when that is a directory under `~/.agent/tasks` holding `SPEC.md` (else the task above a review directory whose marker was accepted): in Claude Code the transcript's token usage (`tokens`: the last call's context, as the harness reports it; input, output and cache counts summed beside it), in Cursor `tokens=unknown` with `duration_ms`, `tool_calls` and `messages` from the payload; `crew ls --cost` and `crew report` show it per task, per agent kind and harness. For a `crew-builder` run, the hook also saves the same reply, from its `## Implementation Report` heading to the end, into the task its `crew-task: <TASK_DIR>` line names: `REPORT.md`, or `REPORT.part-<a>-<b>.md` when the prompt's header (the lines around `crew-task:`) has one `TASK_RANGE: <a>-<b>` line, and both when that line ends in `final`. Each is written atomically beside `<report name>.provenance.json`; a report that fails `report-check` against `gates.json` is saved with a `WARN` line in PROGRESS.md. A builder run it cannot save (no heading, no task line, two ranges in the header) prints `no report saved: <reason>`. `save-out --from-transcript <transcript>` (the reply extracted as the hook does, its marker checked against `.expect`) or `crew-task.py report save <TASK_DIR>` (the reply on stdin) is the fallback when an `.out.md` or the report is still missing after the agent stops. |
| `stop` (`Stop` / `stop`) | Agent loop ends | `memory-capture-prompt.sh` queues one memory review. `usage.sh` (`crew-task.py usage stop`), when the event carries token counts (Cursor's `stop`), appends the session's raw counts as one `cursor_stop` METRIC (`conversation_id`, `generation_id`, `model`, `loop_count`, `input`, `output`, `cache_read`, `cache_write`) to the conversation's task: the one its first recorded stop resolved to (from the first workspace root's git state alone, as `task-context` resolves it), kept in `~/.agent/state/cursor-conversations.txt`, so a branch switch never splits a conversation across tasks. With no task it records nothing and logs nothing; a payload missing `conversation_id` or `generation_id` is skipped and logged. The readers take, per conversation, each count's rise over the previous `stop` (all of it after a fall), and skip a `generation_id` already seen, so a running total and per-loop counts are both read without counting anything twice (see [Harness facts](#harness-facts-2026-11-27)); per-loop counts would read low, so `crew ls --cost`, `crew report` and the TUI show `cursor sessions` as approximate (`~`). Other outcomes go to `~/.agent/state/usage.log`. `crew-task.py gc --only telemetry` prunes both hook logs and the conversation file by age (`sessions_days`). |
| `idle` (`Notification` `idle_prompt`; none in Cursor) | `idle_prompt` | `notify-idle.sh` shows a macOS banner ("<repo> (<branch>) needs your input") and never activates or focuses an application. It stays quiet in a background job (`CLAUDE_JOB_DIR` set), shows at most one banner per session every 10 minutes (the last one's time is in `~/.agent/memory/.sessions/<session>.notified`), and `EL_CAPITAN_NOTIFY=off` turns it off. It always exits 0. |
| `session_start` (`SessionStart` / `sessionStart`) | Session begins | Loads bounded memory context, re-renders a stale rendered file, applies the spec status policy, and refreshes the anchor |

## Rules

Each rule is a function of its guard and has its own off switch (`EL_CAPITAN_GUARD_<RULE>=off`). A rule that fails is
skipped with one stderr line; credentials instead denies the commands it scans. Every denial is logged to
`~/.agent/state/guard.log`: time, rule, harness and a `cksum` of the command or path, never its text.

| Rule | Guard | Where | What it refuses |
|---|---|---|---|
| `owner-only` | shell | everywhere | `crew-task.py restore-status ... --acc*` from any agent shell; `task_gates.restore_status` also refuses `--accept` in code unless stdin is a terminal, and `crew-task.py` accepts no abbreviation of it |
| `worker-tree` | shell | everywhere | `git checkout`, `switch`, `restore`, `reset --hard` in a tree with a fresh `.crew-worker.lock` (6 hours); the builder is exempt through `CREW_WORKER_TASK` |
| `credentials` | shell | everywhere | a secret (gitleaks) in what `git commit` records, or in every branch's and tag's commits on no remote for `git push` and `gh pr create`; without gitleaks, or when gitleaks fails, only those commands are denied; a commit whose git index cannot be read is not scanned (one stderr line), and the push scan still runs ("run install.sh"), and `crew doctor` fails |
| `too-complex` | shell | everywhere | a command nesting more payloads than the normaliser reads |
| `spec-owner` | file | everywhere | a task `SPEC.md` titled for another task's slug, written over a spec past DRAFTING (a DRAFTING spec may be retitled; `mark-approved` records the approved title's slug) |
| `destructive-git` | shell | everywhere | `reset --hard`, `clean` with force, force pushes (`-f`, `--force`, `+ref`, `--force-if-includes` without a lease) |
| `local-pr-ref` | shell | Cursor | `gh pr checkout` |
| `pr-repo` | shell | Cursor | `gh pr create` without `--repo` when an `upstream` remote exists |
| `source-edit` | shell | everywhere | a `>`/`>>` redirect, `tee`, `sed -i`, `perl -i`, or a `python -c`, `node -e` or `perl -e` snippet or heredoc that writes an existing tracked file or a task's `SPEC.md`, `PROGRESS.md` or `.task-id`; scratch and new files pass, and a Python snippet whose write target is no literal counts every literal but dict data and read paths |
| `task-files` | both | everywhere | an `rm`, `unlink` or `find -delete` of a task record, task directory or the tasks root; Cursor's Delete of a task record |
| `status` | file | Cursor | a write that moves a task `SPEC.md`'s `## Status`, or cannot be applied exactly |

`destructive-git`, `task-files` and `source-edit` stay dispatcher rules in Claude Code too: a deny rule matches a
command's prefix, so it misses `git -C <tree> reset --hard` (the form crew agents use), a removal named by a variable or
resolved against the cwd, and a write's target, which only these rules parse.

**Demoted rules** run only where the harness's manifest declares no deny rule that holds in the session's mode
(`deny` in `src/crew/harness/<id>.json`, the event's `deny_rules`): the Cursor app, the Cursor CLI and Codex until a
probe shows theirs hold. In Claude Code the permission rules of its manifest hold them, and the probe below shows they
hold unattended:

- `deny`: `gh pr checkout`;
- `gh pr create` is allowed only as `gh pr create --repo ...`, so an implied target prompts;
- `zsh-equals` is gone: the `personal.mdc` edit-tool rule says to quote a `===` separator.

The allowlist is narrow: git reads plus `add`, `commit`, `fetch`, `switch -c` and `push` (its force forms are the shell guard's),
`gh pr view|diff`, `gh pr create --repo`, `gh api -X GET`; no blanket `git`, `gh`, `sed`, `cp`, `mv`, `curl` or
`source`. `install.sh --sandbox` also turns on Claude Code's sandbox for Bash and its child processes. The Cursor CLI
gets its own deny tokens (`deny_tokens` in `cursor-cli.json`) in `~/.cursor/cli-config.json` when that file exists,
and Codex its `prefix_rule(decision = "forbidden")` rules in `~/.codex/rules/el-capitan.rules` (both unverified live).

**Deleted** (no rule replaces them): the write boundary, a failed scan blocking every command, local PR ref reads,
`cp`/`mv` into task dirs, inline imports of the task modules, a shell fed by an unreadable pipe, edits of evidence files,
and the `SPEC.md` name and case. A shell write to a task record that `source-edit` cannot parse is caught after the fact
by the Status integrity check (TAMPERED).

**Branch protection.** Protect `main` on GitHub (require a pull request, block force pushes and deletion): it is the
boundary the force-push rules approximate. Nothing here sets it up.

## Harness facts (2026-11-28): do deny rules hold unattended?

A scratch repository with one uncommitted change and the project rule `{"permissions":{"deny":["Bash(git reset --hard*)"]}}`,
then `claude -p "<run: cd . && git reset --hard>" --permission-mode bypassPermissions --max-turns 3`:

| Run | Result | Uncommitted change |
|---|---|---|
| el-capitan guards on | blocked by the destructive-git guard (hooks run before permission rules) | kept |
| `EL_CAPITAN_GUARDS=off` (the deny rule alone) | "Permission to use Bash with command cd . && git reset --hard has been denied." | kept |

So a Claude Code `permissions.deny` rule holds in headless (`-p`) mode, under `bypassPermissions` (the most permissive
mode) and for a compound command. Not probed: `claude --bg` background jobs, which run the same permission engine but
do not inherit the launching shell's environment; and Cursor auto-run, which has no deny list in the app, so the
demoted rules stay dispatcher rules there.

## Harness facts (2026-11-27)

Observed by a temporary probe hook (since removed) that logged payload and variable names, never
values, while the owner ran one shell command, one file edit and two Task subagents in Cursor.

- **Cursor edits.** `preToolUse` reports an edit as `tool_name` `Write` with `tool_input`
  `{file_path, content}`, the whole file. `afterFileEdit` carries `file_path` and `edits[]` of
  `{old_string, new_string}`. The Status guard reads `tool_name`, `file_path` and `content`, so its
  Cursor mapping holds.
- **Cursor shell.** `beforeShellExecution` carries `command`, `cwd`, `sandbox` and the common fields.
  `preToolUse` also fires for the shell, with `tool_name` `Shell` (not `Bash`) and `tool_input`
  `{command, cwd, timeout}`; a Cursor `preToolUse` matcher for the shell is `Shell`.
- **Fail-closed guards.** Cursor accepts `{}` from a `failClosed` guard: the shell command, the edit
  and both subagents ran, and nothing was blocked.
- **Cursor subagents.** `subagentStart` carries `subagent_id`, `subagent_type`, `subagent_model`,
  `task`, `is_parallel_worker`, `parent_agent_id`, `tool_call_id` and `transcript_path`.
  `subagentStop` carries `agent_transcript_path`, `child_conversation_id`, `subagent_id`,
  `subagent_type`, `status`, `task`, `duration_ms`, `message_count`, `tool_call_count`, `loop_count`
  and `transcript_path`; it has no reply-text field, so a hook would read the reply from
  `agent_transcript_path`. The Task tool's `tool_input` is `{description, prompt, subagent_type}`,
  plus `resume` and `run_in_background` when used: Cursor's Task can resume a subagent.
- **No subagent limits.** No field reports a tool or turn limit on a subagent, only counts, so a
  persona's `tool_budget` is guidance in Cursor (`readonly` is its only restriction).
- **Cursor usage.** `stop` carries `input_tokens`, `output_tokens`, `cache_read_tokens`,
  `cache_write_tokens`, `model_id`, `loop_count`, `status`, `conversation_id` and `generation_id`, once
  per agent loop. The probe logged field names, not values, so whether the counts are that loop's or
  the conversation's running total is not established; `usage.sh` stores them raw and the
  readers count only rises. **`stop` does not fire for subagents:** in the probe's log, three `stop`s
  match the parent's three turns, and none falls between a `subagentStart` and its `subagentStop`, the
  two parallel subagents included. A subagent's tokens are therefore unknown in Cursor; its
  `subagentStop` reports `duration_ms`, `tool_call_count` and `message_count`, and no `subagent_model`
  (only `subagentStart` carries that).
- **Cursor also runs Claude-format hooks.** Every event was logged a second time from the
  Claude-format registrations (`PreToolUse`, `SubagentStop`, `Stop`), usually twice, in the same
  second as the Cursor entry. Cursor loads Claude Code hook settings (most likely
  `~/.claude/settings.json` and the repository's `.claude/settings.json`) and does not merge an
  identical command, so el-capitan's Claude hooks ran in Cursor beside the template's. Those payloads
  carry `cursor_version` (and the environment `CURSOR_VERSION`). [Harness
  adapters](#harness-adapters) says what runs now.
- **Claude Code runs an identical command once.** Its hooks reference: "If you define the same
  handler in more than one settings file, it runs once"
  ([code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks), read 2026-11-28). A hook
  in both `~/.claude/settings.json` and a project's `.claude/settings.json` is no duplicate there.
- **Cursor `subagentStop`, documented** ([cursor.com/docs/agent/hooks](https://cursor.com/docs/agent/hooks),
  [cursor.com/docs/agent/subagents](https://cursor.com/docs/agent/subagents), read 2026-11-28): input
  `subagent_type`, `status` (`completed`, `error`, `aborted`), `task` (the dispatch prompt),
  `description`, `summary` (an output summary, not the reply), `duration_ms`, `message_count`,
  `tool_call_count`, `loop_count`, `modified_files`, and `agent_transcript_path`, which may be null;
  common fields `conversation_id`, `generation_id`, `transcript_path` (the parent's, or null) and
  `workspace_roots`. It fires each time the subagent finishes, again after a `followup_message`
  continuation with `loop_count` + 1; `followup_message` is read only for `completed`, and each entry's
  `loop_limit` (default 5) caps the continuations. All matching hooks from every source run. Not
  documented: the transcript format, whether it is flushed when the hook fires, and stop-token fields.
- **Cursor `subagentStop`, observed only** (the probe and the live capture log, 2026-11-28):
  `subagent_id`, `parent_conversation_id`, `parent_agent_id` and, in one of two variants,
  `child_conversation_id`; the event fires twice per subagent within a second, once per variant; the
  transcript is `<conversation>/subagents/<subagent_id>.jsonl` beside the parent's
  `<conversation>/<conversation>.jsonl`; in two live reviews the payload's `agent_transcript_path` did
  not lead the hook to it; `stop` carries token counts; and Cursor loads Claude-format hook settings
  (its third-party-hooks page returned 404). So `capture-reply.sh` reads the marker from `task`,
  tries the payload's path, the derived `subagents/` path and a nonce scan, logs each candidate's size
  when none holds a marker, and treats the second fire as a repeat.
- **Claude Code `SubagentStop`** ([code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks),
  read 2026-11-28): input `stop_hook_active`, `agent_id`, `agent_type`, `agent_transcript_path` and
  `last_assistant_message`; `{"decision": "block", "reason": ...}` keeps the subagent running and
  delivers `reason` as its next instruction.
- **`CLAUDE_JOB_DIR` in hooks: an inference, not observed.** A `claude --bg` job started with
  `EL_CAPITAN_PROBE=1` in the launching shell ran its `SessionStart` and `Stop` hooks, and the probe
  logged nothing: background sessions are most likely started by Claude Code's background service
  and do not inherit that shell's environment, so an environment switch such as `EL_CAPITAN_*` may
  not reach hooks in a background job. The job's tool shell has `CLAUDE_JOB_DIR`, and hooks are
  spawned by the same process, so it most likely reaches them; `notify-idle.sh` keeps its check.
  Idle banners from background jobs would show it does not, and the hook would then need another
  signal.

## Harness adapters

A harness is a manifest, `src/crew/harness/<id>.json` (each capability with a value or a declared `fallback`: the
canonical events it maps, whether deny rules hold per mode, where rules, agents and skills go, the access classes),
and an adapter, `<id>.py`, with `render()`, `normalize()` and `encode()`. `install.sh` writes what every `render()`
returns (`harness_install apply`), and `crew doctor` compares the installed files with it.

| Harness | Live | Registers | Rules, agents, skills |
|---|---|---|---|
| `claude-code` | verified | `~/.claude/settings.json` (merged per config dir) | imports of `~/.claude/el-capitan`, `~/.claude/agents`, `~/.claude/skills` |
| `cursor` | verified | the local plugin's `hooks/hooks.json` | `~/.cursor/plugins/local/el-capitan/{rules,agents}`; skills in `~/.cursor/skills` |
| `cursor-cli` | unverified | the same plugin (local plugins load in the CLI) | the plugin; deny tokens in `~/.cursor/cli-config.json` |
| `codex` | unverified | `~/.codex/hooks.json` (Claude-shaped) | `~/.codex/agents/*.toml`, `~/.agents/skills`, `~/.codex/rules/el-capitan.rules` |

Cursor also runs the Claude-format registrations of `~/.claude/settings.json`: those payloads carry `cursor_version`,
and while the plugin's `hooks/hooks.json` is installed the claude-code adapter answers them with nothing (the plugin
registers every event itself); without it the copy is judged, as Cursor, with no deny rules.

Install copies the rules and `contract.json` into `~/.agent/hooks`, so the rules, the contract and the registrations
change together and only at install; a `git pull` changes none of them. A guard (`fail: closed`) that is missing,
crashes or times out denies the call, and so does a contract of another version than `crew-hook.py`: re-run
install.sh. Each registration's timeout is its rules' plus 5 s, so `crew-hook.py` answers before the harness stops it.
One case stays open by design: when the launcher itself is gone (`~/.agent/venv` deleted), the harness reports a
failed command and, except Cursor's `failClosed` guards, lets the call through; a registration that blocked on a
missing launcher would block every command, the fix included. `crew doctor` names a missing launcher. Install retires
the layout before the adapters, registrations before scripts: el-capitan's entries in `~/.cursor/hooks.json` (by the
settings merger's own match, `hooks_retirement.retired`), then the links in `~/.cursor/rules`, `~/.cursor/agents` and
`~/.claude/hooks`.

To probe a harness, `~/.agent/bin/crew-hook.py --record <dir>` saves each payload's structure (values replaced) until
`crew-hook.py --record off`; the parity suite's fixtures (`evals/fixtures/harness/`) come from those files.

## Status integrity

**The threat model, honestly.** An agent with a shell that runs as your user can always forge local
files: a path in a variable, `eval` of built text, an encoded command, or a script written now and run
later all hide the target from any hook, and the same agent can write PROGRESS.md and SPEC.md that way.
So the real approval gate is the harness's permission prompt on the gate commands (`mark-approved`,
`mark-done --force`, `restore-status`, which have no allow rule) plus your review of the PR. The
record and the tripwire below catch the accidental and literal routes, and make a deliberate bypass
visible; they are not a lock.

**The record.** Every status move `crew-task.py` makes (the gates, `mark-done --force`,
`restore-status`) appends a `TRANSITION: <from> → <to> ... [gate]` line to the task's PROGRESS.md
before it writes the spec (a failed spec write appends a stamped line back). A line counts only when
its text, before any `CREW_WORKFLOW`/`CREW_MEMBER` JSON suffix, ends with the stamp, and the spec's
`## Status` must equal the target of the newest such line (DRAFTING when there is none; a spec with no
Status yet passes). `crew-tool.py task-log --step` refuses a status target or the stamp in its text or in those
variables (exit 2). `crew ls`, the TUI and `crew-task.py reconcile` read both files they already read
and show a mismatch as `TAMPERED (spec says X, crew-task recorded Y)`; `mark-approved`,
`mark-implementing`, `mark-done`, `ship` and the reconcile holds refuse it with the same words and
write nothing.

**The tripwire.** Where deny rules do not hold (Cursor) the `status` and `task-files` rules refuse an Edit or Write that moves the
Status and a Delete or `rm` of a task record; in Claude Code the `ask` rule on task specs and the `deny`
rules on `rm` under `~/.agent/tasks` do. The `owner-only` rule refuses `restore-status --acc*` from an
agent, and `crew-task.py` accepts no abbreviated option. Every other write to a task record is caught
by the integrity check above.

A task with no stamped line is legacy, from before the stamp: its recorded status is the newest
transition line, typed or untyped. A legacy DONE spec recorded IMPLEMENTING, or nothing, was closed by
hand before `mark-done` stamped: `crew ls --all` notes it `closed outside crew-task`; recorded
DRAFTING, APPROVED or ON-HOLD it skipped implementation and is TAMPERED. A stamped task is strict: a
DONE spec without a stamped DONE is TAMPERED. So is a task with a `.task-id` and a missing or empty
PROGRESS.md, unless its Status is DRAFTING or absent, so deleting the record never makes a task lenient.

`crew-task.py restore-status <TASK_DIR>` writes the stamped status back (or DRAFTING when nothing is
recorded; it refuses a legacy status no gate stamped) and prompts like the gates. `--accept <note>`
records the spec's status with the note; only the owner runs it, in their own terminal: the
`owner-only` rule refuses it from any agent shell, and the command itself refuses it without a terminal.

## The contract

A rule reads the normalised event on stdin and answers in no harness's format: a deny is `{"deny": MESSAGE}`, no
objection is exit `0` and no output, context is plain text, a stop's request to go on is `{"followup": TEXT}`, and a
rule that cannot read its input reports one line and exits `0`. Within a guard, a rule that fails is skipped with one
stderr line; the credentials rule denies the commands it scans instead. Each contract rule names its fail mode and
timeout (`.claude/hooks/contract.json`); the adapter turns them into the harness's registration. The shared preamble
is `.claude/hooks/lib/hook.sh`.

## How a guard reads a command

The shell guards read a command the way the shell runs it, through one normaliser in
`.claude/hooks/lib/hook.sh`: quotes are removed with their content kept, `sh|bash|zsh -c` payloads,
`eval` and `$(...)` are read as commands of their own, the command is split on `;`, `&&`, `||` and
`|`, each segment is judged in its own tree (`cd`, `git -C`), and git's global options (`--no-pager`,
`-c k=v`, `-C`) are skipped. `git` behind a runner (`timeout`, `xargs`, `find -exec`, `nice -n 5`,
`sudo -u me`) is still git; a quoted `"git"` argument of another command is not. A quoted commit
message or a heredoc body stays data, except a heredoc, here-string or `echo`/`printf` text fed to a
shell with no `-c`, which is read as its script; what any other pipe feeds a shell is not read. A
command nesting more payloads than the normaliser reads is denied (`too-complex`).

The normaliser is [`shfmt`](https://github.com/mvdan/sh) (v3.14.1, from the `shfmt-py` wheel in
`~/.agent/venv`): the command is parsed into a real bash syntax tree (`shfmt --to-json`, read by
`lib/segments.jq`), which reads `$(...)` inside double quotes and in unquoted heredoc bodies
correctly. A command it cannot parse, or one that nests too deeply for the tree to stay small, is
denied as `too-complex`. `crew doctor` fails when shfmt is missing.

## Turning a guard off

Every blocking hook honours an off switch read from the harness's own environment (export it in the
shell that starts Claude Code or Cursor; a prefix on the agent's command does not reach the hook):
`EL_CAPITAN_GUARDS=off` turns them all off, and `EL_CAPITAN_GUARD_<RULE>=off` turns off one rule,
where `<RULE>` is the rule name upper-cased with `-` as `_` (`EL_CAPITAN_GUARD_CREDENTIALS`,
`..._WORKER_TREE`, `..._OWNER_ONLY`, `..._TOO_COMPLEX`, `..._SPEC_OWNER`, `..._STATUS`,
`..._DESTRUCTIVE_GIT`, `..._LOCAL_PR_REF`, `..._PR_REPO`, `..._SOURCE_EDIT`, `..._TASK_FILES`). Every
denial names both switches on its one line. The guards are a safety boundary, so turn one off for a session, not as a standing setting.

The review-address gate is the user's answer in `crew-address-review` Step 3; no hook or permission
rule records it.

The notification hook is not a guard and has its own switch: `EL_CAPITAN_NOTIFY=off`, set in the
same harness environment, turns the idle banner off. It needs `osascript`, so it is macOS-only; on
other systems it exits silently.
