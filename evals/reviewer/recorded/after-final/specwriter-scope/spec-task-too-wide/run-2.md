Only SPEC.md exists in the checkout, so I could not verify any path the spec names.

**Critical**

**Task 2** — "write `.claude/hooks/notify-idle.sh`, register it in `.claude/settings.json` and `.cursor/hooks.template.json`, add its install entry to `.claude/merge_claude_settings.py`, document it in `docs/hooks.md` and `README.md`, and add its rows to `evals/tools/hook_cases.py`" bundles the script, three registration files, two docs and the test rows.
This touches 7 files and 4 concerns: code, registration, docs and tests. A failed verify can't be traced to one edit, and a half-finished task leaves a registered hook with no script or a script with no test rows. Task 2 also has no verify line.
Split it into: (a) the script plus its `hook_cases.py` rows, verified by the test command; (b) the registration in `settings.json`, `hooks.template.json` and `merge_claude_settings.py`; (c) the docs. Give each a verify line.

**Tasks 2 and 3** — Task 3 "add the off switch to `docs/hooks.md`" edits the same file that Task 2 already edits.
Task 2 does not mention `EL_CAPITAN_NOTIFY`. Nothing in the tasks implements the switch, and Task 3 only documents it, so criterion 2 (`EL_CAPITAN_NOTIFY=0` turns it off) has no implementing task. Any `hook_cases.py` rows from Task 2 also don't say they cover the off switch.
Fold the docs line into the docs task, and add the `EL_CAPITAN_NOTIFY` check to the script task and its test rows.

**Important**

**Tests / Unit** — The Unit layer is the only one, and it covers a hook that the harness runs and that reads and writes a rate-limit stamp file.
Task 1 (the stamp helper in `hook.sh`) has no test, and `hook_cases.py` rows are placed in Task 2, so nothing proves the 60 s second-call suppression. The spec also doesn't say whether `test_hook_cases.py` exists or reads `hook_cases.py`. Also, the spec never says how the desktop notification is mocked, so the test can't run without a display.
Say which stub replaces the notifier, and add a test layer that runs the hook as a subprocess (the real exit code and stamp-file behavior). Name the case rows that cover the rate limit, the off switch and exit 0.

**Acceptance criteria** — "exits 0 on every path" and "shows one notification naming the job" have no stated way to check them.
The builder can't mark them `[x]` unless a named test case covers them. No bullet says "inspect X" or names a test.
Tie each criterion to a named `hook_cases.py` row or an `rg` command.

Verdict: 4 finding(s), 7 unverified: `.claude/hooks/lib/hook.sh`, `.claude/settings.json`, `.cursor/hooks.template.json`, `.claude/merge_claude_settings.py`, `docs/hooks.md`, `evals/tools/hook_cases.py`, `evals/test.sh`/`evals/tools/test_hook_cases.py`. The checkout contains only SPEC.md.