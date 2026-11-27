Assessment: request-changes — the gate is called structural, but the approval marker is not bound to a specific table presentation, and the state is a single global slot. Both let it fail open or deadlock.

1. [attention · 4] **`.claude/hooks/review-address-gate.sh:22`** — approval is not bound to a presentation, so a stale `approved` satisfies a new `pending`
```
if [ -f "$approved" ]; then
  [ "$(jq -r '.session // empty' "$approved")" = "$session" ] \
    && [ "$(jq -r '.review_dir // empty' "$approved")" = "$armed_review" ] && hook_allow
```
Nothing ever deletes `approved`, and neither marker carries a nonce or timestamp. If the skill re-presents a table for the same review directory in the same session (a re-run, or a second round after new findings), the old approval already matches and edits are allowed with no new answer. That is the exact failure the gate exists to prevent.
Fix: have the skill remove `approved` when it writes `pending`. Better, put a generated `id` in `pending` and require `approved.id == pending.id`.

2. [attention · 4] **`.claude/hooks/review-address-approval.sh:19`** — an answer of `none` deadlocks the gate for the rest of the session
```
# `none` authorizes no edit, so it records nothing
```
After `none`, `pending` stays and no `approved` is written. Every later Edit or Write in that session is denied with "has no approval yet. Reply with the fixes…", including unrelated work. The only way out is to delete the marker by hand. Once `none` is accepted as an answer, the gate has no way to close.
Fix: on `none`, remove `pending` (or write a `resolved` state the gate treats as allow).

3. [attention · 3] **`.claude/hooks/review-address-gate.sh:7`** — one global `pending`/`approved` slot per `$HOME`
```
state="$HOME/.agent/review-address"
pending="$state/pending"
```
Two concurrent Claude sessions overwrite each other's marker. The second session's `pending` disarms the first, because `armed_session != session` leads to `hook_allow`. The same shared dir is used by every config dir that install merges into.
Fix: key the files by session id (`pending.$session`, `approved.$session`).

4. [attention · 4] **`.claude/settings.json:19`** — the "structural" claim is weaker than the comment says
```
"matcher": "Edit|Write|MultiEdit",
```
The approval hook's header says "the model cannot write `approved` itself". Only Edit, Write and MultiEdit are gated, so the model can still run `sed -i`, `tee` or `echo > …/approved` through Bash. It can also write the approval marker or delete `pending` that way. The gate stops the accidental case but not a model that routes around it.
Fix: add a Bash matcher that denies writes to `~/.agent/review-address/` and to the repo while pending. At minimum, drop the "cannot" claim from the comments and the skill.

5. [attention · 3] **`.claude/hooks/review-address-gate.sh:8`** — failure modes are fail-open and inconsistent
```
set -euo pipefail
...
[ "$(jq -r '.session // empty' "$approved")" = "$session" ]
```
Only the `pending` reads are guarded with `|| true`. A corrupt `approved`, or a missing `jq`, makes the script exit 1. Claude Code treats only exit 2 as blocking, so the edit goes through. An empty `session_id` also goes straight to `hook_allow`. A security gate should fail closed, or at least fail the same way in each case.
Fix: guard every `jq` read. Where `pending` exists and the state cannot be parsed, call `hook_deny`.

6. [needs more info · 2] **`.claude/hooks/review-address-gate.sh:10`** — `lib/hook.sh` and the install path are not in the package
```
. "$(dirname "$0")/lib/hook.sh"
```
The diff adds no `lib/hook.sh`, and the working directory has none. Settings point at `$HOME/.claude/hooks/review-address-gate.sh`, but the files live at `.claude/hooks/` in this repo. Does install copy `lib/` and the two new scripts? Does `lib/hook.sh` define `hook_field`, `hook_allow` and `hook_deny`? If either is missing, the PreToolUse hook errors (non-2), the gate silently never fires, and the safety feature is off with no signal.

The approval regex in `review-address-approval.sh:18` also treats a bare "ok" or "yes" as approval, even when it answers an unrelated question while `pending` is armed. I am not raising it as a finding because it follows from the design.