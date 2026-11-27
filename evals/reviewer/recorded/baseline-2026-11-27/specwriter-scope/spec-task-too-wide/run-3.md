**Critical**

**Task 2** — One task edits six files and mixes five kinds of work.

The task writes a new script, registers it in two config files, edits an installer, edits two docs, and adds eval rows. That is far over the 1–2 file limit. One failure leaves the hook half-registered, and no single check can isolate which part broke.

Split it into: (a) write `notify-idle.sh`; (b) register it in `.claude/settings.json` and `.cursor/hooks.template.json`; (c) add the install entry in `.claude/merge_claude_settings.py`; (d) add rows to `evals/tools/hook_cases.py`; (e) one final docs task.

**Task 1–2** — The spec has no per-task acceptance checks, and the one test command is unverified.

Tasks carry no `verify:` command. The only check is `bash evals/test.sh evals/tools/test_hook_cases.py`. That path names a different file from the `evals/tools/hook_cases.py` that Task 2 edits. Neither file exists in the working directory, so I could not confirm either. The `.claude/hooks/lib/hook.sh` path in Task 1 is also unconfirmed. The directory is empty apart from SPEC.md, so the builder cannot tell which file is real. Task 1's stamp helper has no check of its own, and the "exits 0 on every path" criterion has no inspection path.

Reconcile the two test filenames. Give each task a runnable check, for example `bash -n` on the script or an `rg` for the registration entry. Give each acceptance bullet a `verify:` line.

**Important**

**Task 3** — This task duplicates the docs work in Task 2 and edits the same file.

Task 2 already documents the hook in `docs/hooks.md`, and Task 3 edits that file again to add the off switch. The off-switch behaviour (`EL_CAPITAN_NOTIFY=0`) is not implemented in any task, so Task 3 documents a switch that nothing builds. Task 3 also comes after the code tasks and has no check.

Move the `EL_CAPITAN_NOTIFY` check into the `notify-idle.sh` task. Fold the docs into a single final docs task.

**Task 1–2** — The ordering dependency is implicit, and atomicity is not declared.

Task 2's script presumably sources the helper from Task 1. Registering the hook before the script exists would break the session. No `> Tasks N and N+1 are atomic` note says which tasks must ship together.

State the dependency. Order the registration tasks after the script task, and mark them atomic if they cannot ship separately.

**Consider**

**Spec** — The "at most once a minute" rule has no stated stamp location or clock source.

Without a stamp path, such as a file under `$TMPDIR`, the builder has to guess it. The test for "a second within 60 s shows nothing" then cannot be written reliably.

Name the stamp path and the time source in Task 1.

Verdict: 4 finding(s), 3 unverified: `.claude/hooks/lib/hook.sh`, `evals/tools/hook_cases.py` vs `test_hook_cases.py`, and `.claude/merge_claude_settings.py`. The other referenced paths could not be confirmed either, because the working directory has no repo files.