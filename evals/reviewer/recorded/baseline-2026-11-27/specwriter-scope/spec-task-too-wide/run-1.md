**Critical**

**Task 2** — One task touches 7 files: the hook, `settings.json`, `hooks.template.json`, `merge_claude_settings.py`, `docs/hooks.md`, `README.md` and `hook_cases.py`.

This is far beyond the 1–2 file limit. A failure partway through leaves the hook half-registered, and no single acceptance check can isolate it. The hook script, the two registrations plus the installer entry, the docs, and the test rows are separate units.

Fix: split Task 2 into (a) the hook script plus its `hook_cases.py` rows, (b) the registration in `settings.json`, `hooks.template.json` and `merge_claude_settings.py`, and (c) the docs. Mark (a) and (b) atomic if the intermediate state breaks.

**Task 2 / Tests** — The only test command is `evals/tools/test_hook_cases.py`, and no task creates or verifies it. The hook rows are in the same oversized task as the hook, and no row covers the rate limit, the `EL_CAPITAN_NOTIFY=0` switch, or the exit-0 paths.

The Completion Protocol therefore cannot show that the acceptance criteria hold. The criteria also have no `verify:` or inspection path.

Fix: name the `hook_cases.py` rows that cover each criterion (the 60 s limit, the off switch, exit 0), and give each criterion a `verify:` command.

**Important**

**Task 3** — The off switch is only documented, in `docs/hooks.md`, in Task 3. Nothing in the tasks implements `EL_CAPITAN_NOTIFY=0` in the hook. Task 2 also edits `docs/hooks.md`, so the two tasks overlap on that file and the switch is not covered by Task 2's wording.

The off-switch behaviour could ship undocumented or unimplemented, and the doc edit is split from the doc task it belongs to.

Fix: put the switch check in the hook task (Task 2a) and merge the docs into one final docs task.

**Task 1** — Task 1's helper lives in `.claude/hooks/lib/hook.sh`, and Task 2 depends on it. The ordering is correct but not stated. The stamp's location, format, and the "idle job" identity (per job or global) are not defined, so the builder has to guess.

The per-minute limit could be keyed globally or per job, and "a second within 60 s shows nothing" is ambiguous between the two.

Fix: state the stamp file path and the key, and the helper's function signature.

**Unverified:** The workspace contains only SPEC.md. I could not verify that any of the referenced paths exist: `.claude/hooks/lib/hook.sh`, `.claude/settings.json`, `.cursor/hooks.template.json`, `.claude/merge_claude_settings.py`, `docs/hooks.md`, `README.md`, `evals/tools/hook_cases.py`, `evals/tools/test_hook_cases.py` and `evals/test.sh`.

Verdict: 4 finding(s), 9 unverified (the paths listed above)