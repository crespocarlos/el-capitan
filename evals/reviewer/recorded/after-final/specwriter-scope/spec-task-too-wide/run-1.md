**Critical**

**Task 2** — "write `.claude/hooks/notify-idle.sh`, register it in `.claude/settings.json` and `.cursor/hooks.template.json`, add its install entry to `.claude/merge_claude_settings.py`, document it in `docs/hooks.md` and `README.md`, and add its rows to `evals/tools/hook_cases.py`." This one task touches 7 files and mixes the hook script, two registrations, the installer, two docs and the eval cases. If the builder gets the script wrong, or the settings JSON malformed, the single verify line can't show which edit broke it. Three failed verify runs then mark the whole task failed.

Split it into separate tasks: (a) the script plus its `hook_cases.py` rows, with the test run as its verify line; (b) the registrations in `.claude/settings.json`, `.cursor/hooks.template.json` and `merge_claude_settings.py`; (c) the docs. Each task needs its own verify line.

**Task 2 / Task 3** — "document it in `docs/hooks.md`" overlaps with "add the off switch to `docs/hooks.md`". Task 2 already documents the hook, so the builder may write the `EL_CAPITAN_NOTIFY=0` text twice or in conflicting places. Task 3 is also not a separate concern: the off switch is part of the script's behaviour, and nothing in Task 2 implements it. If the loop stops after Task 2, the hook has no off switch, and the criterion `EL_CAPITAN_NOTIFY=0` has no implementing task. The only mention of it is a docs edit.

Move the `EL_CAPITAN_NOTIFY` check into the script task and its test rows. Fold the docs line into the single docs task and delete Task 3.

**Important**

**Tasks 1–3** — no task has a verify line, although the builder runs one per task. Task 1 (the stamp helper in `.claude/hooks/lib/hook.sh`) has no check at all. The `## Tests` command (`bash evals/tools/test_hook_cases.py` via `evals/test.sh`) runs only at the end, so a failure there can't be tied to a task. Add a verify line per task, e.g. `bash -n .claude/hooks/lib/hook.sh`, `python -m json.tool` on the JSON files, and `rg EL_CAPITAN_NOTIFY docs/hooks.md`.

**## Tests** — the change crosses a process boundary (a hook the harness runs, plus an installer), but only `### Unit` is listed. The command also names `evals/tools/test_hook_cases.py` as an argument to `evals/test.sh`, which I could not verify exists. Nothing exercises the merge script or the 60 s rate limit end to end. Add an `### Integration` layer, e.g. running `notify-idle.sh` twice within 60 s and asserting one notification and exit 0, plus a run of `merge_claude_settings.py` on a fixture.

**Unverified**: the workspace holds only SPEC.md, so none of these paths could be checked: `.claude/hooks/lib/hook.sh`, `.claude/settings.json`, `.cursor/hooks.template.json`, `.claude/merge_claude_settings.py`, `docs/hooks.md`, `README.md`, `evals/tools/hook_cases.py`, `evals/test.sh` and `evals/tools/test_hook_cases.py`. The task list doesn't say whether these files exist or are to be created, so the builder will stall if they are absent. State which files are new.

Verdict: 3 finding(s), 9 unverified