# Hooks

`install.sh` registers hooks in both harnesses: `.claude/settings.template.json` is merged into
`~/.claude/settings.json`, and `.cursor/hooks.template.json` into `~/.cursor/hooks.json`. Each hook is
one small file under `.claude/hooks/`; read any of them before you install. The guards among them
are a security boundary: [SECURITY.md](../SECURITY.md) says what they protect and how to report a
bypass.

| Hook | Trigger | What it does |
|---|---|---|
| `PreToolUse` / Cursor `beforeShellExecution` | Bash | Seven rules, one per file under `guard/`: `owner-only.sh` (`crew-task.py restore-status ... --acc*` from any agent: the owner runs it in their own terminal); `task-files.sh` (a tripwire for a shell write whose literal target is an existing task `SPEC.md` or `.task-id`, its `PROGRESS.md`, or a review's `*.expect`, `*.provenance.json` or `*.out.md`: an output redirect, `tee`, `dd of=`, a `truncate` operand, the destination of `install` and `ln`, both ends of `mv`, a `sed -i`/`perl -i`/`ruby -i`/`awk -i inplace` file, a Python snippet's write target as `lib/py_write_targets.py` parses it; any `cp`/`mv`/`rsync` destination inside a task directory, a whole task folder copied over another included; an `rm`, `unlink` or `find -delete` of a protected file, a task directory or the tasks root; and inline Python that imports the task modules next to the tasks root; the path is resolved and compared case-insensitively by `lib/spec_guard.py --shell`, reads and the crew tools pass, and a `SPEC.md` or `.task-id` not there yet passes only as a new task's first write (no PROGRESS.md and no `.task-id` yet). Without shfmt the awk normaliser reads the redirects and words with the same coverage. It does not see a path in a variable, `eval` of built text, an encoded command or a script run later: those are caught after the fact by the Status integrity check below the table); `destructive-git.sh` (destructive git: `git reset --hard`, `git clean` with force, force pushes including `-f`, `--force` next to `--force-with-lease`, `--force-if-includes` without a lease, and `+ref`); `local-pr-ref.sh` (`gh pr checkout` and local `refs/pull/...`, `pull/<n>` or `pull/*` refs, never a path such as `src/pull/x.ts`); `source-edit.sh` (`python -c`, `node -e`, `perl -e` snippets and heredocs that rewrite a tracked file: a Python snippet is parsed, never run, by `lib/py_write_targets.py`, so only a write's target counts and a tracked file it only reads passes; Node, Perl, and a Python snippet that does not parse or holds a write the parser cannot resolve (a loop variable, an f-string, a name bound twice, `subprocess`, `os.open`, `fileinput` in place, `exec`, `eval`, `getattr`, `__import__`), are denied when any quoted literal in the snippet names a tracked file); `zsh-equals.sh` (a bare unquoted `=word` that zsh expands as a command path and which aborts the rest of the line: `echo ====` and longer, while a quoted separator and a lone `=` pass); `worker-tree.sh` (`git checkout`, `switch`, `restore` and `reset --hard` in a tree that holds a fresh `.crew-worker.lock`; advisory defence for the tree a worker holds, main checkout included; the builder is exempt through `CREW_WORKER_TASK`). A sixth, `credentials.sh`, blocks commits whose staged lines, or the files a `git add` / `git commit -a` in the same command stages, match known secret formats, and `gh pr create` without `--repo` when an `upstream` remote exists. |
| `PreToolUse` / Cursor `preToolUse` | Write, Edit | `check-write-boundary.sh` blocks writes outside the active worktree; it allows `~/.agent`, `~/.claude`, `~/.cursor`, `/tmp`, the review pipeline's temp directory, and a background job's `<config dir>/jobs/<job>/tmp` for every Claude config dir `~/.agent/install-manifest.json` records that resolves to a direct child of `$HOME` named `.claude*` (any agent can write the manifest, so no other entry counts). |
| `PreToolUse` / Cursor `preToolUse` | Write, Edit, MultiEdit | `check-task-spec-owner.sh` blocks a `SPEC.md` whose slug does not match the task directory's recorded slug. Through `lib/spec_guard.py` it also blocks, in an existing task `SPEC.md`, any Edit, MultiEdit or Write that changes the `## Status` value as `task_status` reads it (universal newlines, so a lone `\r` counts as a line break), leaves a second `## Status` heading, or cannot be applied exactly (an `old_string` missing or not unique, an unknown tool, or a payload carrying another tool's fields: Write is read by `content`, Edit by `old_string`/`new_string`/`replace_all`, MultiEdit by `edits`); a new `SPEC.md` whose Status is anything but empty or DRAFTING; and any write to a task's `.task-id`, its `PROGRESS.md` or a review's `*.expect`, `*.provenance.json` and `*.out.md`, which only crew tools write. The path is decided first (realpath, names compared case-insensitively), so a write anywhere else never loads the Status reader; for a task spec the check fails closed. Use `crew-task.py mark-approved`, `mark-implementing` or `mark-done` to move a status. Every other edit (checkbox ticks, text, amendments) passes. Install adds your `~/.agent/tasks`, as an absolute path, to `permissions.additionalDirectories` and allows `Edit(~/.agent/tasks/**)` (Claude Code matches Write and MultiEdit against Edit rules), so task files are written without a prompt; this guard runs before that allow. A Bash command never reaches this hook: `guard/task-files.sh` refuses its literal writes, and the Status integrity check catches the rest. |
| `UserPromptSubmit` | Each turn | `mode-anchor.sh` prints the active task, status, branch, and task directory so a long session does not drift out of the pipeline. The line is computed once by `spec-status-reconcile.sh` and cached. |
| `PostToolUse` | Bash, Write, Edit | Emits local JSON telemetry |
| `PostToolUse` / Cursor `afterShellExecution` | Bash | `record-pr.sh` records the PR a successful `gh pr create` printed on its task (`crew-task.py record-pr`). Only a command with a real `gh … pr create` segment counts (the `lib/hook.sh` normaliser; text in an `echo` or a string does not), and only when its output holds exactly one distinct PR URL; with several it records nothing and lists them. It asks `gh pr view` for the head branch and matches the task's repo (the base, or the fork the head owner names) and `branch`. The single open match wins over DONE and ABANDONED ones; an IMPLEMENTING match gains the PR and goes through `mark-done`, any other single match only gains the PR; several record nothing and print each `mark-done` command. A head branch that is only some task's `spec_branch` records nothing and names that task; no match at all, in a repo that already has tasks, becomes a minimal DONE task with no spec. Any other command ends in shell; the outcome is Claude's additional context. Session-start reconcile still catches PRs opened any other way. |
| `SubagentStop` (Claude Code) | Subagent ends | `capture-reply.sh` saves a reviewer persona's reply (`crew-review-findings.py capture`) when a line of the dispatch prompt is the `crew-review-out: <review dir> <persona> <nonce>` marker that `crew-review-findings.py expect` printed. The position is not the check: the nonce is, so the reply is saved only when `<persona>.expect` holds the same nonce (or, with no `.expect`, for a resume of the agent that saved it). The reply is the `SubagentHandback` message, else the transcript's last assistant text, else the payload's `last_assistant_message`; a resume of the same agent is saved with `--resume`, another agent's reply is never overwritten, and `.expect` is removed after the save. The same hook reads the transcript's token usage (`tokens`: the last call's context, as the harness reports it; input, output and cache counts summed beside it) and appends an `agent_end` METRIC (with `agent_id`, so a resumed agent counts once) to the task a `crew-task: <TASK_DIR>` prompt line names, only when that is a directory under `~/.agent/tasks` holding `SPEC.md` (else the task above a review directory whose marker was accepted); `crew ls --cost` and `crew report` total it per task. For a `crew-builder` run, the hook also saves the same reply, from its `## Implementation Report` heading to the end, into the task its `crew-task: <TASK_DIR>` line names: `REPORT.md`, or `REPORT.part-<a>-<b>.md` when the prompt's header (the lines around `crew-task:`) has one `TASK_RANGE: <a>-<b>` line, and both when that line ends in `final`. Each is written atomically beside `<report name>.provenance.json`; a report that fails `report-check` against `gates.json` is saved with a `WARN` line in PROGRESS.md. A builder run it cannot save (no heading, no task line, two ranges in the header) prints `no report saved: <reason>`. Cursor's `subagentStop` carries no reply text, only the subagent's transcript path, and its `stop` carries token counts (see [Harness facts](#harness-facts-2026-11-27)); no hook reads either yet, so Cursor keeps the manual `save-out` and `crew-task.py report save <TASK_DIR>` (the reply on stdin), and records no usage. |
| `Notification` (Claude Code only) | `idle_prompt` | `notify-idle.sh` shows a macOS banner ("<repo> (<branch>) needs your input") and never activates or focuses an application. It stays quiet in a background job (`CLAUDE_JOB_DIR` set), shows at most one banner per session every 10 minutes (the last one's time is in `~/.agent/memory/.sessions/<session>.notified`), and `EL_CAPITAN_NOTIFY=off` turns it off. It always exits 0. |
| `SessionStart` | Session begins | Loads bounded memory context, applies the spec status policy, and refreshes the anchor (Cursor: `sessionStart` hook via `cursor-memory-context.sh`) |

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
  `cache_write_tokens`, `model_id`, `loop_count` and `status`, once per agent loop.
- **Cursor also runs Claude-format hooks.** Every event was logged a second time from the
  Claude-format registrations (`PreToolUse`, `SubagentStop`, `Stop`), usually twice, in the same
  second as the Cursor entry. Cursor loads Claude Code hook settings (most likely
  `~/.claude/settings.json` and the repository's `.claude/settings.json`) and does not merge an
  identical command, so el-capitan's Claude hooks ran in Cursor beside the template's. Those payloads
  carry `cursor_version` (and the environment `CURSOR_VERSION`). [Each hook in
  Cursor](#each-hook-in-cursor) says what runs now.
- **Claude Code runs an identical command once.** Its hooks reference: "If you define the same
  handler in more than one settings file, it runs once"
  ([code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks), read 2026-11-28). A hook
  in both `~/.claude/settings.json` and a project's `.claude/settings.json` is no duplicate there.
- **`CLAUDE_JOB_DIR` in hooks: an inference, not observed.** A `claude --bg` job started with
  `EL_CAPITAN_PROBE=1` in the launching shell ran its `SessionStart` and `Stop` hooks, and the probe
  logged nothing: background sessions are most likely started by Claude Code's background service
  and do not inherit that shell's environment, so an environment switch such as `EL_CAPITAN_*` may
  not reach hooks in a background job. The job's tool shell has `CLAUDE_JOB_DIR`, and hooks are
  spawned by the same process, so it most likely reaches them; `notify-idle.sh` keeps its check.
  Idle banners from background jobs would show it does not, and the hook would then need another
  signal. `check-write-boundary.sh` does not depend on it.

## Each hook in Cursor

Cursor runs the Claude-format registrations of `~/.claude/settings.json` beside its own
`~/.cursor/hooks.json`. The template is `.claude/settings.template.json`, not the checkout's
`.claude/settings.json`, so the checkout's project settings (permissions only) add no third copy.
Every hook the template registers has one row:

- **stands down**: in Cursor's Claude-format copy (a PascalCase `hook_event_name` and a
  `cursor_version` in the payload) the script exits 0 with no output before anything else
  (`hook_stand_down` in `lib/hook.sh`), because its Cursor-template counterpart does the work. It
  stands down only while `~/.cursor/hooks.json` registers that counterpart under the event
  `.claude/hooks/lib/cursor-counterparts.json` names for it, as the command
  `bash "$HOME/.claude/hooks/<counterpart>"` followed by nothing but `2>/dev/null` and `; exit 0`,
  and for a fail-closed guard only with `failClosed: true`. A comment that names the script, a
  prefixed or extended command, or an entry under another event is no counterpart, so the hook keeps
  running and a guard never runs nowhere. `CURSOR_VERSION` alone does not count: Claude Code started
  from Cursor's terminal may inherit it.
- **Tool names.** The probe saw Cursor report an edit as `Write` to both its own `preToolUse` and
  the Claude-format `PreToolUse`, so the template's `Write|Edit` matcher covers every edit the
  Claude-format `Write|Edit|MultiEdit` matcher did; Cursor's shell is `beforeShellExecution`, which
  fires for every command whatever the tool is called.
- **keeps running**: no Cursor-template counterpart; the Claude-format copy is the one that runs.
- **dropped**: exits 0 with no output in Cursor's copy (`hook_dropped_in_cursor`), for the reason
  given.

`crew doctor` warns about a script registered both in `~/.cursor/hooks.json` and in a Claude-format
file Cursor loads for the current repository (however each spells the command) that does not stand
down by the same match, and lists the commands behind it.

| Hook | Claude event | In Cursor | Counterpart or reason |
|---|---|---|---|
| `guard/destructive-git.sh` | `PreToolUse` Bash | stands down | `beforeShellExecution` `guard/destructive-git.sh`, fail-closed |
| `guard/local-pr-ref.sh` | `PreToolUse` Bash | stands down | `beforeShellExecution` `guard/local-pr-ref.sh`, fail-closed |
| `guard/source-edit.sh` | `PreToolUse` Bash | stands down | `beforeShellExecution` `guard/source-edit.sh`, fail-closed |
| `guard/task-files.sh` | `PreToolUse` Bash | stands down | `beforeShellExecution` `guard/task-files.sh`, fail-closed |
| `guard/owner-only.sh` | `PreToolUse` Bash | stands down | `beforeShellExecution` `guard/owner-only.sh`, fail-closed |
| `guard/zsh-equals.sh` | `PreToolUse` Bash | stands down | `beforeShellExecution` `guard/zsh-equals.sh` |
| `guard/worker-tree.sh` | `PreToolUse` Bash | stands down | `beforeShellExecution` `guard/worker-tree.sh`, fail-closed |
| `guard/credentials.sh` | `PreToolUse` Bash | stands down | `beforeShellExecution` `guard/credentials.sh`, fail-closed |
| `check-write-boundary.sh` | `PreToolUse` Write, Edit | stands down | `preToolUse` `check-write-boundary.sh`, fail-closed |
| `check-task-spec-owner.sh` | `PreToolUse` Write, Edit | stands down | `preToolUse` `check-task-spec-owner.sh`, fail-closed |
| `log-tool-use.sh` | `PostToolUse`, `PostToolUseFailure` | stands down | `postToolUse`, `postToolUseFailure` `log-tool-use.sh` |
| `record-pr.sh` | `PostToolUse` Bash | stands down | `afterShellExecution` `record-pr.sh` |
| `memory-context.sh` | `SessionStart` | stands down | `sessionStart` `cursor-memory-context.sh` |
| `memory-capture-prompt.sh` | `Stop` | stands down | `stop` `memory-capture-prompt.sh` |
| `agents-refresh.sh` | `SessionStart` | keeps running | from the Claude-format load |
| `spec-status-reconcile.sh` | `SessionStart` | keeps running | from the Claude-format load |
| `mode-anchor.sh` | `UserPromptSubmit` | keeps running | from the Claude-format load |
| `notify-idle.sh` | `Notification` | keeps running | from the Claude-format load, when Cursor sends `idle_prompt` |
| `capture-reply.sh` | `SubagentStop` | dropped | it reads Claude Code's transcript and reply fields, which Cursor's subagent payload lacks, so it would only report "no marker"; Cursor keeps the manual `save-out` |

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
Status yet passes). `crew-progress.py` refuses a status target or the stamp in its text or in those
variables (exit 2). `crew ls`, the TUI and `crew-task.py reconcile` read both files they already read
and show a mismatch as `TAMPERED (spec says X, crew-task recorded Y)`; `mark-approved`,
`mark-implementing`, `mark-done`, `ship` and the reconcile holds refuse it with the same words and
write nothing.

**The tripwire.** The Status guard refuses Edit/Write to PROGRESS.md, `.task-id` and review evidence;
`guard/task-files.sh` refuses the literal shell writes and removals of them, copies into a task
directory, and inline Python that imports the task modules next to the tasks root (`$HOME` spelled
out counts as literal). `guard/owner-only.sh` refuses `restore-status --acc*` from an agent, and
`crew-task.py` accepts no abbreviated option.

A task with no stamped line is legacy, from before the stamp: its recorded status is the newest
transition line, typed or untyped. A legacy DONE spec recorded IMPLEMENTING, or nothing, was closed by
hand before `mark-done` stamped: `crew ls --all` notes it `closed outside crew-task`; recorded
DRAFTING, APPROVED or ON-HOLD it skipped implementation and is TAMPERED. A stamped task is strict: a
DONE spec without a stamped DONE is TAMPERED. So is a task with a `.task-id` and a missing or empty
PROGRESS.md, unless its Status is DRAFTING or absent, so deleting the record never makes a task lenient.

`crew-task.py restore-status <TASK_DIR>` writes the stamped status back (or DRAFTING when nothing is
recorded; it refuses a legacy status no gate stamped) and prompts like the gates. `--accept <note>`
records the spec's status with the note; only the owner runs it, in their own terminal:
`guard/owner-only.sh` refuses it from any agent.

## The contract

Every hook follows one contract: blocking is exit `2` with one line on stderr (Cursor's shell events
get their own JSON deny), no objection is exit `0` and no output, and a hook that cannot read its
input reports one line and exits `0`. In Claude Code, failures are non-blocking except for
`guard/credentials.sh`, registered `onFailure: "block"`; an unexpected error once its secret scan has
started blocks the commit, while one before it (unreadable input, a missing `jq`, a normaliser
failure) reports a line and lets the command through. An off switch releases either. In Cursor, a
hook crash, timeout or invalid JSON fails open unless the entry sets `failClosed: true`, so every
security guard has it (every `guard/` rule but the advisory `zsh-equals.sh`, plus
`check-write-boundary.sh` and `check-task-spec-owner.sh`; observers never). Because Cursor reads
silence from such a hook as a failure, each prints `{}`, an empty decision with no permission, when
it has no objection; a failure before it reads the event (no `jq`) prints nothing and so blocks.
Install's merge keeps the flag and `crew doctor` fails an installed guard without it. Without `jq` on
PATH the merge registers them `failClosed: false` with one warning, and `crew doctor` fails a
fail-closed install on a machine without `jq` (every Cursor call would be blocked). The shared
preamble is `.claude/hooks/lib/hook.sh`.

## How a guard reads a command

The shell guards read a command the way the shell runs it, through one normaliser in
`.claude/hooks/lib/hook.sh`: quotes are removed with their content kept, `sh|bash|zsh -c` payloads,
`eval` and `$(...)` are read as commands of their own, the command is split on `;`, `&&`, `||` and
`|`, each segment is judged in its own tree (`cd`, `git -C`), and git's global options (`--no-pager`,
`-c k=v`, `-C`) are skipped. `git` behind a runner (`timeout`, `xargs`, `find -exec`, `nice -n 5`,
`sudo -u me`) is still git; a quoted `"git"` argument of another command is not. A quoted commit
message or a heredoc body stays data, except a heredoc, here-string or `echo`/`printf` text fed to a
shell with no `-c`, which is read as its script; a shell fed by any other pipe (`curl ... | bash`)
is denied, and so is a command nesting more payloads than the normaliser reads.

The normaliser has two parsers. [`shfmt`](https://github.com/mvdan/sh) is optional and preferred:
when it is on PATH, the command is parsed into a real bash syntax tree (`shfmt --to-json`, read by
`lib/segments.jq`), which reads `$(...)` inside double quotes and in unquoted heredoc bodies
correctly. Without it, when it cannot parse the command, or when the command is over 16 KiB or
nests too deeply for the tree to stay small, an awk tokenizer reads it instead, so a parse failure
never lets through what awk would block. Install it with `brew install shfmt` (CI pins v3.14.1).
`crew doctor` reports which parser is active.

## Turning a guard off

Every blocking hook honours an off switch read from the harness's own environment (export it in the
shell that starts Claude Code or Cursor; a prefix on the agent's command does not reach the hook):
`EL_CAPITAN_GUARDS=off` turns them all off, and `EL_CAPITAN_GUARD_<NAME>=off` turns off one, where
`<NAME>` is the file name upper-cased with `-` as `_` (`EL_CAPITAN_GUARD_DESTRUCTIVE_GIT`,
`..._LOCAL_PR_REF`, `..._SOURCE_EDIT`, `..._TASK_FILES`, `..._OWNER_ONLY`, `..._ZSH_EQUALS`, `..._WORKER_TREE`, `..._CREDENTIALS`,
`..._CHECK_WRITE_BOUNDARY`, `..._CHECK_TASK_SPEC_OWNER`). Every denial names both switches on its
one line. The guards are a safety boundary, so turn one off for a session, not as a standing setting.

The review-address gate is the user's answer in `crew-address-review` Step 3; no hook or permission
rule records it.

The notification hook is not a guard and has its own switch: `EL_CAPITAN_NOTIFY=off`, set in the
same harness environment, turns the idle banner off. It needs `osascript`, so it is macOS-only; on
other systems it exits silently.
