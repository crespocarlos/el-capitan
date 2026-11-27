Assessment: request-changes — the gate fails open in several ways: one global marker slot, an approval that is never consumed, and a matcher that skips Bash.

Read beyond the package: none. The package holds three files, and `lib/hook.sh` and the skill are not among them.

Approach: redirect — keep the structural gate, but have the PreToolUse hook return `permissionDecision: "ask"` while a table is pending, so the platform's own approval prompt replaces the custom approval hook and regex.
Alternatives considered:
- Don't build the approval hook; let PreToolUse return `ask` while `pending` exists. This wins. The owner approves at the native prompt, so there is no prompt-regex classifier and no `approved` file to go stale or be forged. It loses only the "all/none/numbers" conversational flow.
- Scope the markers by session (`pending-$session_id`) and consume `approved` on use. This is the minimal repair of the chosen design and fixes findings 1 and 2. It still keeps the regex approval path.
- Prose-only gate. This was already tried and did not hold.

1. [attention · 4] **`.claude/hooks/review-address-approval.sh:20`** — `approved` is never cleared or consumed, so a later table is born approved
```
jq -n --arg s "$armed_session" --arg r "$armed_review" ... > "$approved"
```
The gate allows when `approved` matches the session and review_dir. Nothing deletes `approved` when the skill writes a new `pending`. If the owner approves, then re-runs `crew review address` on the same review directory in the same session, the old `approved` still matches. Edits are allowed before the owner answers the second table, which is the failure the gate exists to prevent.
Fix: the skill deletes `approved` when it writes `pending`. Better, store an approval nonce or timestamp in `pending` and require `approved` to carry it, or use per-session files.

2. [attention · 4] **`.claude/hooks/review-address-gate.sh:14`** — state is a single global slot shared by all sessions
```
pending="$state/pending"
approved="$state/approved"
```
Session A presents a table and writes `pending`. Session B then presents its own table and overwrites it. Session A's `armed_session` no longer matches, so A's gate allows edits with no approval. The same applies to B's `approved` overwriting A's. Concurrent Claude sessions are normal here, since the install covers every config dir.
Fix: key the files by session (`pending-$session_id`, `approved-$session_id`).

3. [attention · 4] **`.claude/settings.json:19`** — the matcher leaves the Bash path ungated
```
"matcher": "Edit|Write|MultiEdit",
```
While the table is pending, the model can run `sed -i` or `cat > file` through Bash, or `echo > ~/.agent/review-address/approved`. This breaks both "must not edit anything" and the claim that the model cannot write `approved`. NotebookEdit is also uncovered.
Fix: add Bash and NotebookEdit to the matcher, with a Bash guard that denies writes to the state dir and to files under the review. Or use the `ask` approach above, which applies to every tool.

4. [attention · 3] **`.claude/hooks/review-address-gate.sh:23`** — the gate fails open on a `jq` error
```
if [ -f "$approved" ]; then
  [ "$(jq -r '.session // empty' "$approved")" = ...
```
The script runs under `set -euo pipefail`, and this `jq` call has no `|| true`. A corrupt or truncated `approved` file makes `jq` fail and the script exit 1. Claude Code treats exit 1 as a non-blocking error, so the edit proceeds. A missing `jq` also makes `armed_session` empty, which takes the `hook_allow` branch. I could not read `lib/hook.sh` to confirm what `hook_allow` and `hook_deny` emit.
Fix: when `pending` matches the session, make every failure path call `hook_deny`, for example `|| true` on the `jq` calls. Check for `jq` explicitly and fail closed.

5. [attention · 3] **`.claude/hooks/review-address-approval.sh:17`** — any bare `ok`, `yes` or number approves, and the numbers are not enforced
```
grep -Eqi '^[[:space:]]*(all|yes|ok|...)...|^[[:space:]]*[0-9]+(...)*$'
```
While a table is pending, an owner reply of "ok" or "2" to an unrelated question opens the gate for every edit. A reply of "1,3" opens it for fix 2 as well, because only the fact of approval is recorded. The `prompt` field is stored but nothing reads it.
Fix: record the selected set and have the gate check the edit's file against it. Or drop the regex and use the native `ask` prompt.

6. [attention · 3] **`.claude/settings.json:21`** — the hook path assumes `$HOME/.claude`, but the install targets each Claude config dir
```
bash \"$HOME/.claude/hooks/review-address-gate.sh\"
```
Under a `CLAUDE_CONFIG_DIR` install the hooks may not live at `$HOME/.claude/hooks`. A missing script makes the PreToolUse hook error non-blockingly, so the gate silently never runs. The approval hook's `; exit 0` also hides a missing script. Nothing in the package shows that install copies the hooks or `lib/hook.sh`.
Fix: use `${CLAUDE_CONFIG_DIR:-$HOME/.claude}` in the commands, and have install verify that the hook files exist.