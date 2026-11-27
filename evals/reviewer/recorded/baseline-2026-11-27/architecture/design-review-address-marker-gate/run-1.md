Assessment: request-changes — the gate is armed by one global marker file that never clears, so it can deadlock a session, and a stale `approved` marker can bypass it.

1. [blocking · 4] **`.claude/hooks/review-address-gate.sh:22`** — a stale `approved` marker satisfies a newly written `pending`
```
if [ -f "$approved" ]; then
  [ "$(jq -r '.session // empty' "$approved")" = "$session" ] \
    && [ "$(jq -r '.review_dir // empty' "$approved")" = "$armed_review" ] && hook_allow
```
Approval is matched only on session and review_dir, with no ordering or nonce. If the skill presents a table again for the same review directory in the same session (a re-run, or a second round after new findings), the earlier `approved` still matches and edits pass with no new approval. This is the exact failure the gate exists to prevent. Nothing in the diff deletes `approved` when `pending` is written, and the skill change that writes `pending` is not in this diff.
Fix: include a per-presentation id (a nonce or timestamp) in `pending`, copy it into `approved`, and compare it in the gate. Or have the skill `rm -f approved` when it writes `pending`.

2. [attention · 4] **`.claude/hooks/review-address-approval.sh:17`** — an answer of `none`, or any phrase outside the regex, leaves the session denied for every edit
```
# `none` authorizes no edit, so it records nothing
if printf '%s' "$prompt" | grep -Eqi '^[[:space:]]*(all|yes|ok|...
```
`none` records nothing and nothing clears `pending`, so all later Edit/Write calls in that session are denied, including unrelated ones. The deny message tells the user to reply `none`, which doesn't release the gate. Natural replies such as "1,3 but skip 2", "all except 4", or "fix 1 and 3" don't match the regex either, so they leave the gate armed with no way out except hand-deleting the file.
Fix: on `none`, remove `pending`. Have the skill clear `pending` when it finishes. Make the deny message say how to release the gate.

3. [attention · 3] **`.claude/hooks/review-address-gate.sh:7`** — one global `pending` file, shared by every session, fails open
```
state="$HOME/.agent/review-address"
pending="$state/pending"
...
[ -n "$session" ] && [ "$armed_session" = "$session" ] || hook_allow
```
A second concurrent session that presents a table overwrites `pending`, so the first session's gate silently becomes "another session, allow". Empty `session_id`, a missing `jq`, or an unreadable marker all fall through to allow as well. The record is single-slot and fails open, so the structural guarantee only holds with one session at a time.
Fix: key the markers by session, for example `$state/$session/{pending,approved}`. Decide explicitly whether parse failures should deny.

4. [attention · 3] **`.claude/settings.json:20`** — the gate covers only file-edit tools
```
"matcher": "Edit|Write|MultiEdit",
```
`Bash` (`sed -i`, `tee`, redirects) and `NotebookEdit` are not matched. A model blocked on Edit can write the same files through Bash, so the claim that the gate is structural only holds for the listed tools.
Fix: add `NotebookEdit`. Either cover Bash writes while `pending` is armed, or document that the gate is limited to these tools.

5. [needs more info · 3] **`.claude/hooks/review-address-gate.sh:10`** — `lib/hook.sh` is not in the package
The gate sources `$(dirname "$0")/lib/hook.sh` for `hook_field`, `hook_allow` and `hook_deny`. The settings entries run `$HOME/.claude/hooks/review-address-gate.sh`. Does install copy `.claude/hooks/lib/hook.sh` next to the gate in the Claude config dir? If it doesn't, `set -e` aborts the script. For a PreToolUse hook, a non-zero exit other than 2 is non-blocking, so the gate silently stops working. Also check that `hook_deny` exits with the code Claude Code treats as blocking, since I couldn't read it.