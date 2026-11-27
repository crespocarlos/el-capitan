# Hooks

`install.sh` registers hooks in both harnesses: `.claude/settings.json` is merged into
`~/.claude/settings.json`, and `.cursor/hooks.template.json` into `~/.cursor/hooks.json`. Each hook is
one small file under `.claude/hooks/`; read any of them before you install. The guards among them
are a security boundary: [SECURITY.md](../SECURITY.md) says what they protect and how to report a
bypass.

| Hook | Trigger | What it does |
|---|---|---|
| `PreToolUse` / Cursor `beforeShellExecution` | Bash | Five rules, one per file under `guard/`: `destructive-git.sh` (destructive git: `git reset --hard`, `git clean` with force, force pushes including `-f`, `--force` next to `--force-with-lease`, `--force-if-includes` without a lease, and `+ref`); `local-pr-ref.sh` (`gh pr checkout` and local `refs/pull/...`, `pull/<n>` or `pull/*` refs, never a path such as `src/pull/x.ts`); `source-edit.sh` (`python -c`, `node -e`, `perl -e` snippets and heredocs that rewrite a tracked file: a Python snippet is parsed, never run, by `lib/py_write_targets.py`, so only a write's target counts and a tracked file it only reads passes; Node, Perl, and a Python snippet that does not parse or holds a write the parser cannot resolve (a loop variable, an f-string, a name bound twice, `subprocess`, `os.open`, `fileinput` in place, `exec`, `eval`, `getattr`, `__import__`), are denied when any quoted literal in the snippet names a tracked file); `zsh-equals.sh` (a bare unquoted `=word` that zsh expands as a command path and which aborts the rest of the line: `echo ====` and longer, while a quoted separator and a lone `=` pass); `worker-tree.sh` (`git checkout`, `switch`, `restore` and `reset --hard` in a tree that holds a fresh `.crew-worker.lock`; advisory defence for the tree a worker holds, main checkout included; the builder is exempt through `CREW_WORKER_TASK`). A sixth, `credentials.sh`, blocks commits whose staged lines, or the files a `git add` / `git commit -a` in the same command stages, match known secret formats, and `gh pr create` without `--repo` when an `upstream` remote exists. |
| `PreToolUse` / Cursor `preToolUse` | Write, Edit | `check-write-boundary.sh` blocks writes outside the active worktree; it allows `~/.agent`, `~/.claude`, `~/.cursor`, `/tmp`, the review pipeline's temp directory, and a background job's `<config dir>/jobs/<job>/tmp` for every Claude config dir `~/.agent/install-manifest.json` records that resolves to a direct child of `$HOME` named `.claude*` (any agent can write the manifest, so no other entry counts). |
| `PreToolUse` / Cursor `preToolUse` | Write, Edit, MultiEdit | `check-task-spec-owner.sh` blocks a `SPEC.md` whose slug does not match the task directory's recorded slug. Through `lib/spec_guard.py` it also blocks, in an existing task `SPEC.md`, any Edit, MultiEdit or Write that changes the `## Status` value as `task_status` reads it (universal newlines, so a lone `\r` counts as a line break), leaves a second `## Status` heading, or cannot be applied exactly (an `old_string` missing or not unique, an unknown tool, or a payload carrying another tool's fields: Write is read by `content`, Edit by `old_string`/`new_string`/`replace_all`, MultiEdit by `edits`); a new `SPEC.md` whose Status is anything but empty or DRAFTING; and any write to a task's `.task-id` or a review's `*.expect`, `*.provenance.json` and `*.out.md`, which only crew tools write. The path is decided first (realpath, names compared case-insensitively), so a write anywhere else never loads the Status reader; for a task spec the check fails closed. Use `crew-task.py mark-approved`, `mark-implementing` or `mark-done` to move a status. Every other edit (checkbox ticks, text, amendments) passes. Install adds your `~/.agent/tasks`, as an absolute path, to `permissions.additionalDirectories` and allows `Edit(~/.agent/tasks/**)` (Claude Code matches Write and MultiEdit against Edit rules), so task files are written without a prompt; this guard runs before that allow. **Not covered:** a Bash command that rewrites `SPEC.md` (`cat >`, a heredoc, a script) never reaches this hook; the harness's own Bash prompt is the only check on it. |
| `UserPromptSubmit` | Each turn | `mode-anchor.sh` prints the active task, status, branch, and task directory so a long session does not drift out of the pipeline. The line is computed once by `spec-status-reconcile.sh` and cached. |
| `PostToolUse` | Bash, Write, Edit | Emits local JSON telemetry |
| `PostToolUse` / Cursor `afterShellExecution` | Bash | `record-pr.sh` records the PR a successful `gh pr create` printed on its task (`crew-task.py record-pr`). Only a command with a real `gh … pr create` segment counts (the `lib/hook.sh` normaliser; text in an `echo` or a string does not), and only when its output holds exactly one distinct PR URL; with several it records nothing and lists them. It asks `gh pr view` for the head branch and matches the task's repo (the base, or the fork the head owner names) and `branch`. The single open match wins over DONE and ABANDONED ones; an IMPLEMENTING match gains the PR and goes through `mark-done`, any other single match only gains the PR; several record nothing and print each `mark-done` command. A head branch that is only some task's `spec_branch` records nothing and names that task; no match at all, in a repo that already has tasks, becomes a minimal DONE task with no spec. Any other command ends in shell; the outcome is Claude's additional context. Session-start reconcile still catches PRs opened any other way. |
| `SubagentStop` (Claude Code only) | Subagent ends | `capture-reply.sh` saves a reviewer persona's reply (`crew-review-findings.py capture`) when a line of the dispatch prompt is the `crew-review-out: <review dir> <persona> <nonce>` marker that `crew-review-findings.py expect` printed. The position is not the check: the nonce is, so the reply is saved only when `<persona>.expect` holds the same nonce (or, with no `.expect`, for a resume of the agent that saved it). The reply is the `SubagentHandback` message, else the transcript's last assistant text, else the payload's `last_assistant_message`; a resume of the same agent is saved with `--resume`, another agent's reply is never overwritten, and `.expect` is removed after the save. The same hook reads the transcript's token usage (`tokens`: the last call's context, as the harness reports it; input, output and cache counts summed beside it) and appends an `agent_end` METRIC (with `agent_id`, so a resumed agent counts once) to the task a `crew-task: <TASK_DIR>` prompt line names, only when that is a directory under `~/.agent/tasks` holding `SPEC.md` (else the task above a review directory whose marker was accepted); `crew ls --cost` and `crew report` total it per task. For a `crew-builder` run, the hook also saves the same reply, from its `## Implementation Report` heading to the end, into the task its `crew-task: <TASK_DIR>` line names: `REPORT.md`, or `REPORT.part-<a>-<b>.md` when the prompt's header (the lines around `crew-task:`) has one `TASK_RANGE: <a>-<b>` line, and both when that line ends in `final`. Each is written atomically beside `<report name>.provenance.json`; a report that fails `report-check` against `gates.json` is saved with a `WARN` line in PROGRESS.md. A builder run it cannot save (no heading, no task line, two ranges in the header) prints `no report saved: <reason>`. Cursor's `subagentStop` carries only a summary and no usage, so Cursor keeps the manual `save-out` and `crew-task.py report save <TASK_DIR>` (the reply on stdin), and records no usage. |
| `Notification` (Claude Code only) | `idle_prompt` | `notify-idle.sh` shows a macOS banner ("<repo> (<branch>) needs your input") and never activates or focuses an application. It stays quiet in a background job (`CLAUDE_JOB_DIR` set), shows at most one banner per session every 10 minutes (the last one's time is in `~/.agent/memory/.sessions/<session>.notified`), and `EL_CAPITAN_NOTIFY=off` turns it off. It always exits 0. |
| `SessionStart` | Session begins | Loads bounded memory context, applies the spec status policy, and refreshes the anchor (Cursor: `sessionStart` hook via `cursor-memory-context.sh`) |

## The contract

Every hook follows one contract: blocking is exit `2` with one line on stderr (Cursor's shell events
get their own JSON deny), no objection is exit `0` and no output, and a hook that cannot read its
input reports one line and exits `0`. Failures are non-blocking except for `guard/credentials.sh`,
which alone is registered `onFailure: "block"` / `failClosed: true`; an unexpected error once its
secret scan has started blocks the commit, while one before it (unreadable input, a missing `jq`, a
normaliser failure) reports a line and lets the command through. An off switch releases either.
Because Cursor reads silence from a fail-closed hook as a failure, that one rule also prints an
allow payload when it has no objection. The shared preamble is `.claude/hooks/lib/hook.sh`.

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
`..._LOCAL_PR_REF`, `..._SOURCE_EDIT`, `..._ZSH_EQUALS`, `..._WORKER_TREE`, `..._CREDENTIALS`,
`..._CHECK_WRITE_BOUNDARY`, `..._CHECK_TASK_SPEC_OWNER`). Every denial names both switches on its
one line. The guards are a safety boundary, so turn one off for a session, not as a standing setting.

The review-address gate is the user's answer in `crew-address-review` Step 3; no hook or permission
rule records it.

The notification hook is not a guard and has its own switch: `EL_CAPITAN_NOTIFY=off`, set in the
same harness environment, turns the idle banner off. It needs `osascript`, so it is macOS-only; on
other systems it exits silently.
