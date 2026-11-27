**Task 2** — Task 2 is overloaded (7 files, several concerns), so a failed verify can't be traced to one edit.

Task 2 creates the hook script, registers it in two config files, edits the installer, edits two docs, and adds eval rows. If the Cursor template or the merge script edit fails, the builder can't tell which edit broke the verify. The task also has no verify line of its own.
Fix: Split Task 2 into (a) the hook script plus its `evals/tools/hook_cases.py` rows, (b) registration in `.claude/settings.json`, `.cursor/hooks.template.json` and `.claude/merge_claude_settings.py`, and (c) docs. Give each a verify line.

**Tasks 1–3 / `## Tests`** — None of the referenced paths exist in the workspace, and the spec doesn't say whether they are created or assumed.

A Glob for hook, settings, `test.sh`, `hooks.md` and README files returned nothing. So `bash evals/test.sh evals/tools/test_hook_cases.py` fails immediately with "no such file", and the "add rows to `evals/tools/hook_cases.py`" edit has no target. A builder in a fresh checkout stalls or guesses.
Fix: State that these paths come from the real repository root and name the existing pattern to copy. If they are meant to be new files, add tasks that create them.

**Task 3** — Task 3 edits `docs/hooks.md`, which Task 2 already edits, and it comes after the hook is written.

The off switch `EL_CAPITAN_NOTIFY=0` is therefore not implemented in any task: Task 2 doesn't mention it, and Task 3 only documents it. The result is a hook that ignores the switch, documented as if it worked, and acceptance criterion 2 can't be met. Task 3 also gets the same doc section edited twice.
Fix: Move the `EL_CAPITAN_NOTIFY` check into the hook-script task, and merge the docs edits into one docs task.

**`## Tests` / Acceptance criteria** — Nothing runs the hook as a process, and the criteria have no check for rate limiting or the off switch.

The only test is the unit command `evals/tools/test_hook_cases.py`, and no task gives it a case for a second call within 60 s, for `EL_CAPITAN_NOTIFY=0`, or for exit 0 on every path. The hook is run by the harness, and it also crosses Cursor's template and the installer merge. "One notification naming the job" needs a desktop notifier, which can't run headless. The builder can't mark any criterion `[x]`.
Fix: Add an `### Integration` layer that runs `.claude/hooks/notify-idle.sh` with a stubbed notifier and a temp stamp file. Rewrite the criteria as commands, such as "run twice and count notifier calls", and say that the real desktop popup needs a human check.

**Task 1** — The rate-limit helper can't be verified, and the spec doesn't say where the stamp is stored or how it works.

Task 1 adds a helper to `.claude/hooks/lib/hook.sh` that no hook calls until Task 2, and it has no verify line. If stamp location, clock source or a concurrent-write race are left unspecified, the builder guesses, and a stamp in a shared path could suppress notifications across sessions.
Fix: Specify the stamp path, such as a per-user temp file, and the helper's signature. Add a verify line that sources `hook.sh` and calls the helper twice.

Verdict: 5 finding(s), 4 unverified: `.claude/hooks/lib/hook.sh`, `evals/test.sh`, `evals/tools/hook_cases.py`, `docs/hooks.md` (no matching files found in the workspace, so I couldn't check their contents or whether they are meant to exist).