Assessment: request-changes — the hook re-implements `## Status` parsing in awk, and it disagrees with `task_status.STATUS` on CRLF files, so the guard can be bypassed.

1. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:25`** — CRLF spec makes the guard see no Status section, so any status edit passes
```
status_of() {
  printf '%s\n' "$1" | awk '/^## Status[ \t]*$/ { f = 1; next } ...
```
The awk heading match `^## Status[ \t]*$` does not match `## Status\r`. On a CRLF spec, `status_of` returns empty for both disk and result. `before = after = ""`, so the deny never fires. `task_status.STATUS` explicitly accepts `\r?\n`, so `read_status` still reads the value. An Edit with `old_string` `DRAFTING` and `new_string` `APPROVED` on a CRLF spec passes the hook and moves the status to APPROVED. That defeats Gate 1. Only a CRLF spec triggers it, but the `STATUS` regex handles `\r` on purpose, so the store can hold such files.
Fix: strip `\r` before parsing, for example `printf '%s\n' "$1" | tr -d '\r' | awk ...`. Better, have the hook call the canonical reader (a small python helper importing `task_status.STATUS`), so there is one parser.

2. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:25`** — the hook's "first non-blank line" rule differs from `read_status`
```
f && NF { gsub(...); print; exit }
```
`STATUS` requires the value on the line immediately after the heading. A blank line there gives `read_status` = "". The awk skips blanks and returns the next non-blank line. The hook therefore sees an unchanged status where the tools see a change. The two also differ on a repeated `## Status` heading: awk locks onto the first, while `STATUS.search` moves on to a later heading that has a valid value. In those cases an edit that changes what `read_status` returns can pass. The code comment says the reader is meant to be unique, and this is a second implementation.
Fix: reuse `STATUS` from `task_status.py` in the hook. Alternatively, run `read_status` on a temp file holding the before and after text and compare the results.

3. [nit · 3] **`.claude/hooks/check-task-spec-owner.sh:35`** — an empty Write skips the comparison
```
if [ -n "$written" ]; then
```
A Write with empty `content` skips the check, and it also skips the `disk` read. This clears the Status section without a deny. `read_status` then returns "", which is not an approval, so the cost is losing the status rather than a Gate 1 bypass.
Fix: compare whenever the tool is Write, treating empty content as an after-status of none.