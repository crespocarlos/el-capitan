**Critical**

**Task 2** — "write `.claude/hooks/notify-idle.sh`, register it in `.claude/settings.json` and `.cursor/hooks.template.json`, add its install entry to `.claude/merge_claude_settings.py`, document it in `docs/hooks.md` and `README.md`, and add its rows to `evals/tools/hook_cases.py`" bundles seven files and four concerns: the hook, the registration in two configs, the installer, the docs and the tests. If the hook script fails its verify, the builder can't tell which edit broke it. It gets three verify runs, then the task is marked failed with the whole bundle half-done.

Fix: split Task 2 into separate tasks: the hook script, the registrations (settings, cursor template and merger), the test rows, and the docs. Give each task its own verify line.

**Tasks 1–3** — No task has a verify line, and the only automated check is `bash evals/test.sh evals/tools/test_hook_cases.py` under `## Tests`. The builder runs that only at the end. Task 1's stamp helper and the Task 2 hook have no per-task pass or fail, so the builder can't tell whether a task is done. For example, a helper that never rate-limits is marked done and only fails at the end.

Fix: add a verify line to every task, such as `bash -n` on the script, `python -I -m json.tool` on the JSON, or `rg` for the registered entry.

**Task 3** — "add the off switch to `docs/hooks.md`" is a documentation-only task, but nothing implements `EL_CAPITAN_NOTIFY=0`. Task 2 writes the hook with no mention of the switch, so criterion 2 has no code task. Task 2 already edits `docs/hooks.md`, so Task 3 edits the same file a second time. Only the docs mention the switch, and the hook ignores it.

Fix: move the `EL_CAPITAN_NOTIFY` check into the hook-script task, and fold the doc line into the single docs task.

**Important**

**## Tests** — Only `### Unit` is listed, but the hook is invoked by the harness as a process and sends a desktop notification, so a unit layer alone doesn't cross that boundary. The criteria "exits 0 on every path" and "a second within 60 s shows nothing" need an integration run of the script, with the notification command stubbed and the clock or stamp file controlled. Also, `evals/test.sh` and `evals/tools/test_hook_cases.py` are not in the case directory (it contains only SPEC.md), so I could not confirm they exist.

Fix: add an `### Integration` layer that runs `.claude/hooks/notify-idle.sh` with a stubbed notifier and asserts the exit code and the one-notification-in-60s behavior.

**Acceptance criteria** — "An idle job shows one notification naming the job" needs a desktop session, which the builder doesn't have. The spec doesn't say whether a stub or a human check proves it.

Fix: state that the check uses a stubbed notifier command, or mark the criterion as a human check.

Verdict: 5 finding(s), 4 unverified
Unverified: `.claude/hooks/lib/hook.sh`, `.claude/merge_claude_settings.py`, `evals/test.sh` and `evals/tools/test_hook_cases.py` (the case directory contains only SPEC.md, so these paths are absent). The `docs/hooks.md`, `README.md`, `.claude/settings.json` and `.cursor/hooks.template.json` paths are also absent. The task text doesn't say whether they are created or edited.