# Harness payload fixtures

One JSON file per harness and native hook event (`<event>.json`, or `<event>-<tool>.json` for a tool event), in the
structure the harness sends; `evals/tools/test_harness_parity.py` fills the `{placeholder}` values and runs each
through `crew-hook.py`. A value `"<string>"` is a field whose value no rule reads, as `crew-hook.py --record` writes it.

| Harness | Source | Live |
|---|---|---|
| `claude-code` | the Claude Code hooks reference (input fields per event) | verified |
| `cursor` | the Cursor hooks reference, the key lists in `~/.agent/state/capture-reply.log` and the 2026-11-27 probe log (field names only) | verified |
| `cursor-cli` | the same sources as `cursor`; the CLI loads the same local plugin | unverified: the CLI is not installed |
| `codex` | the Codex hooks docs: Claude-shaped events, `SubagentStop.last_assistant_message` | unverified |

To refresh them from a live harness: `~/.agent/bin/crew-hook.py --record <dir>`, use the harness, then
`crew-hook.py --record off`; `<dir>/<harness>/` holds one redacted payload per event and tool. Copy the structure here
and put the placeholders back where the test fills a value.
