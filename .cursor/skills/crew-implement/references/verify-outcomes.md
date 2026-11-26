# Verify outcomes

`crew-progress.py verify` (and `verify --wait <json>`) is read by its process exit code alone. Step 7
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
`if:`, an expression, a deployment job, a publish command, a workflow that is not CI): the gates ran,
but the run is NOT VERIFIED even when every gate line is `exit=0`. A failed gate is still exit 1.
