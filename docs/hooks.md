# Hooks

`install.sh` registers hooks in both harnesses: `.claude/settings.json` is merged into
`~/.claude/settings.json`, and `.cursor/hooks.template.json` into `~/.cursor/hooks.json`. Each hook is
one small file under `.claude/hooks/`; read any of them before you install. The guards among them
are a security boundary: [SECURITY.md](../SECURITY.md) says what they protect and how to report a
bypass.

| Hook | Trigger | What it does |
|---|---|---|
| `PreToolUse` / Cursor `beforeShellExecution` | Bash | Five rules, one per file under `guard/`: `destructive-git.sh` (destructive git: `git reset --hard`, `git clean` with force, force pushes including `-f`, `--force` next to `--force-with-lease`, `--force-if-includes` without a lease, and `+ref`); `local-pr-ref.sh` (`gh pr checkout` and local `refs/pull/...`, `pull/<n>` or `pull/*` refs, never a path such as `src/pull/x.ts`); `source-edit.sh` (`python -c`, `node -e`, `perl -e` snippets and heredocs that rewrite a tracked file); `zsh-equals.sh` (a bare unquoted `=word` that zsh expands as a command path and which aborts the rest of the line: `echo ====` and longer, while a quoted separator and a lone `=` pass); `worker-tree.sh` (`git checkout`, `switch`, `restore` and `reset --hard` in a tree that holds a fresh `.crew-worker.lock`; advisory defence for the tree a worker holds, main checkout included; the builder is exempt through `CREW_WORKER_TASK`). A sixth, `credentials.sh`, blocks commits whose staged lines, or the files a `git add` / `git commit -a` in the same command stages, match known secret formats, and `gh pr create` without `--repo` when an `upstream` remote exists. |
| `PreToolUse` / Cursor `preToolUse` | Write, Edit | `check-write-boundary.sh` blocks writes outside the active worktree. |
| `PreToolUse` / Cursor `preToolUse` | Write, Edit | `check-task-spec-owner.sh` blocks a `SPEC.md` whose slug does not match the task directory's recorded slug. |
| `UserPromptSubmit` | Each turn | `mode-anchor.sh` prints the active task, status, branch, and task directory so a long session does not drift out of the pipeline. The line is computed once by `spec-status-reconcile.sh` and cached. |
| `PostToolUse` | Bash, Write, Edit | Emits local JSON telemetry |
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

The notification hook (`osascript`, iTerm2 focus) is macOS-only. On other systems it exits silently.
