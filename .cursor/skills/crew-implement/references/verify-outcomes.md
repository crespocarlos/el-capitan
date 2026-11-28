# Verify outcomes

`crew-verify.py` (and `crew-verify.py --wait <json>`) is read by its process exit code alone. Step 6
of `crew-implement` and Step 2c of `crew-commit` act on it as defined here, once. "Hand off / commit"
means the implement handoff or the commit, whichever step you are in.

| Exit | Expected line | What you do |
|---|---|---|
| 0 | every gate line `exit=0` | Verified. Hand off / commit. |
| 1 | a gate line `<name> exit=N`, N nonzero | Failed gate. It blocks: show the lines, do not hand off / commit, ask. |
| 2 or 3 | `verify: NOT VERIFIED ...` | Not a failure and not a pass. Show that line first and ask once whether to hand off / commit. |
| 4 | `still running ... do not hand off` (`--wait` with `--wait-timeout`) | Still running. Do not hand off / commit; wait again or ask. |
| anything else, or the expected line is missing | (a traceback, an error, nothing) | Verify itself failed. Show its stderr, do not hand off / commit, ask. |

A `NOT VERIFIED: partial mirror (N steps skipped)` line means part of the CI was not mirrored (an
`if:`, an expression, a deployment job, a publish command, a CI workflow with a release trigger): the
gates ran, but the run is NOT VERIFIED even when every gate line is `exit=0`. A failed gate is still
exit 1. A workflow with no `push` or `pull_request` trigger is listed as `not CI` and does not count.
How the mirror runs is in `src/crew/TOOLS.md` "Gates and cost".
