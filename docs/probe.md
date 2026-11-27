# Harness probe

A temporary hook, `.claude/hooks/probe.sh`, that settles four facts about the harnesses which the
hooks rely on but no document states. Install registers it in both harnesses, and it does nothing
until you set `EL_CAPITAN_PROBE=1` in the environment that starts the harness. It is removed, with
its registrations, once the results are recorded in [hooks.md](hooks.md).

## What it records

One JSON line per event in `~/.agent/state/probe.log` (mode 600), holding names, never values:

- the harness and the event name;
- the sorted top-level field names of the payload, and those of `tool_input`;
- the value of `tool_name`, which is itself a name;
- the field names inside `edits` items, when a payload has an `edits` list;
- the names of the `CLAUDE_*` and `CURSOR_*` environment variables present;
- for `subagentStart` and `subagentStop`: whether any field holds a string ending in `.jsonl` or longer
  than 200 characters, as true or false plus the field names, never the content.

It never blocks: it always exits 0 and prints nothing, or `{}` on Cursor's `preToolUse`,
`beforeShellExecution` and `subagentStart`, which expect a decision.

It is registered on Claude Code's `SessionStart`, `PreToolUse`, `SubagentStop` and `Stop`, and on
Cursor's `sessionStart`, `preToolUse`, `beforeShellExecution`, `afterFileEdit`, `subagentStart`,
`subagentStop` and `stop`.

## Your steps

Run `./install.sh` from this branch first, so the probe and its registrations are in place.

1. In the terminal that will start each harness, run `export EL_CAPITAN_PROBE=1`, then start the
   harness from that terminal. A variable set later, or as a prefix on an agent's command, does not
   reach the hooks.
2. **Claude Code:** start one background job (`/background`, or your usual way) whose only work is one
   shell command, such as `ls`. Let it finish.
3. **Cursor:**
   1. ask the agent to run one ordinary shell command, such as `ls`;
   2. ask it to make one file edit, such as adding a line to a scratch file. Both must go through:
      this also checks that the fail-closed guards accept `{}` as no objection;
   3. ask it to run one Task subagent that replies with a short sentence.
4. Close both harnesses, run `unset EL_CAPITAN_PROBE`, and paste `~/.agent/state/probe.log` (or
   `tail -n 50 ~/.agent/state/probe.log`) back to the agent.

## What each result decides

| Result | Decides |
|---|---|
| `CLAUDE_JOB_DIR` is in `env` on a Claude Code event from the background job | Whether `notify-idle.sh` keeps its `CLAUDE_JOB_DIR` check. Absent, the check never fires and is removed; `check-write-boundary.sh` already allows the job's `tmp` directory without it. |
| Cursor's `tool_name` and `tool_input_fields` on the edit's `preToolUse`, and `fields`/`edits_fields` on its `afterFileEdit` | Whether the Status guard (`check-task-spec-owner.sh`, `lib/spec_guard.py`) reads Cursor's edit by the right field names. A difference becomes a correction and a row in `evals/tools/hook_cases.py`. |
| Which events fire as the Cursor subagent ends, and on `subagentStop` the `has_jsonl`/`jsonl_fields` and `has_long`/`long_fields` values | Whether a hook can capture a Cursor subagent's reply (a long field) or read its transcript (a `.jsonl` path), and so whether a follow-up spec can replace the manual `save-out` in Cursor. Neither means the manual step stays. |
| The `subagentStart` fields, the subagent's own `preToolUse` lines and whether any turn or tool limit field appears | Whether a `readonly` Cursor subagent is held to any limit beyond read-only, so the docs say whether a persona's `tool_budget` is enforced in Cursor or is guidance only. |

Each finding goes in [hooks.md](hooks.md) with the date of the run; then the probe, its
registrations and this page are removed, and `probe.sh` joins `RETIRED_SCRIPTS` in
`.claude/hooks_retirement.py` so the next install drops its registrations.
