# Security

## What the guards protect

el-capitan lets an AI agent run shell commands and write files in your repositories. Its guard hooks
are a security boundary between the agent and your machine: they block destructive git commands,
commits that carry secrets, writes outside the active worktree, shell-snippet rewrites of tracked
files, and checkouts in a tree a worker holds. [Hooks](docs/hooks.md) lists every guard and what it
reads.

They are a boundary for an agent following its instructions, not a sandbox. A guard reads the
command text the agent sends; a process that is already running, a script the agent wrote earlier,
or a tool outside the two harnesses is not checked. Run untrusted code in a sandbox regardless.

A way to make a guard allow what it documents as blocked (a command form, a quoting trick, a parse
failure that lets a command through) is a security issue, and so is a hook that leaks a secret into
telemetry, a log, or a task file.

## The off switches

Each blocking hook honours an off switch read from the environment of the harness itself:
`EL_CAPITAN_GUARDS=off` turns every guard off, and `EL_CAPITAN_GUARD_<NAME>=off` turns off one (the
names are in [Hooks](docs/hooks.md#turning-a-guard-off)). A prefix on the agent's command does not
reach the hook, so an agent cannot turn a guard off for the command it is running. Turn one off for a
session when you need to, not as a standing setting, and every denial names both switches.

Nothing in el-capitan stops an agent from setting a switch for a later session: the write-boundary
guard allows writes under `~/.claude` and `~/.cursor`, so an agent can add `EL_CAPITAN_GUARDS=off`
to the `env` of `~/.claude/settings.json`, and a shell command can append it to a profile the
harness inherits. The guards are off from the next session that reads it. The only checks on that
write are the harness's own permission prompts. Review an agent's edits to harness settings and shell
profiles. A report of a way to do this unnoticed, or a guard that blocks it, is in scope.

## Supported versions

Only the latest commit on `main` is supported; fixes are not backported to a tagged release.

## Reporting a vulnerability

Report it privately through GitHub: on the repository's **Security** tab, choose **Report a
vulnerability**. Include the command or payload, the harness (Cursor or Claude Code) and its
version, the operating system, and whether `shfmt` was installed, since the guards parse with it
when it is present. Please do not open a public issue or pull request for it.

A confirmed bypass is fixed with a case added to
`evals/tools/hook_cases.py`, so it stays fixed, and credited in the release notes unless you ask
otherwise.
