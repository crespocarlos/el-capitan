**Critical**

**Task 2** — One task edits six files and mixes unrelated work.

It writes the hook, registers it in two config files, edits the installer, edits two docs, and edits the test cases. That is far wider than the 1–2 file limit. A partial failure would leave the hook registered but not installed or not tested, and no single acceptance check can isolate it.

Split it into: (a) `.claude/hooks/notify-idle.sh` alone; (b) registration in `.claude/settings.json` and `.cursor/hooks.template.json`; (c) the install entry in `.claude/merge_claude_settings.py`; (d) the `evals/tools/hook_cases.py` rows; (e) the docs tasks.

**Spec** — The `## Tests` command and every task path point at files that do not exist.

The working directory contains only `SPEC.md`. Neither `evals/test.sh`, `evals/tools/test_hook_cases.py`, nor any `.claude/` or `docs/` path can be found. The builder cannot tell which of these files already exist and which it must create. Task 1 edits `.claude/hooks/lib/hook.sh` as if it exists. I could not verify that the paths exist in the target repo.

Say which files are existing and which are new, and confirm that the test command runs from the repo root.

**Important**

**Task 3** — This task duplicates the documentation work in Task 2 and edits the same file.

Task 2 already documents the hook in `docs/hooks.md`, and Task 3 edits that file again to add the off switch. Task 3 also comes after the hook is written, yet the off switch is behavior that belongs in the hook script. No task implements `EL_CAPITAN_NOTIFY=0` in `notify-idle.sh`.

Add the env check to the hook task, then fold the docs into a single final documentation task.

**Task 1** — The ordering and interface between Task 1 and Task 2 are not stated.

Task 2 depends on the stamp helper's function name, its arguments, and where the stamp is stored. The spec gives none of these, so the builder has to guess or explore. Task 1 also has no standalone acceptance check.

Name the helper's signature and stamp location, and add a `verify:` command for it.

**Acceptance criteria** — The bullets have no `verify:` path.

"Shows one notification" and "exits 0 on every path" give the builder no way to mark them `[x]`. The notification also needs a desktop session. `hook_cases.py` rows could cover the rate limit, the off switch and the exit code, but the spec does not say they will.

Map each bullet to a specific `hook_cases.py` case or an `rg`/`bash` command. State that the notifier is stubbed in tests.

Verdict: 5 finding(s), 1 unverified (paths in the target repo: `evals/test.sh`, `evals/tools/test_hook_cases.py`, `.claude/hooks/lib/hook.sh`)