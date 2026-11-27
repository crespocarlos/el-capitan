Assessment: request-changes — the marker design has no way to clear or invalidate state, so the gate fails open on a second review round and deadlocks after `none`. It also guards only Edit/Write, while the stated goal is that nothing is edited before approval.

1. [blocking · 4] **`.claude/hooks/review-address-gate.sh:23`** (approved-marker lifetime) — an old `approved` marker satisfies every later `pending`
```
if [ -f "$approved" ]; then
  [ "$(jq -r '.session // empty' "$approved")" = "$session" ] \
    && [ "$(jq -r '.review_dir // empty' "$approved")" = "$armed_review" ] && hook_allow
```
Nothing deletes `approved`, and the skill writing a new `pending` doesn't invalidate it. If the same session presents a second table for the same review directory (a re-run, or findings after a fix round), the stale approval matches and edits are allowed with no new consent. The gate is only structural for the first table in each session and review. The marker carries no pairing token such as a nonce or timestamp, so the gate can't tell which table was approved. This is a new defect in the diff.
Fix: have the skill write a unique `id` into `pending`. Have the approval hook copy that `id` into `approved`. Have the gate compare ids, and remove `approved` whenever `pending` is written.

2. [attention · 4] **`.claude/hooks/review-address-gate.sh:16`** (matcher coverage) — the gate can be bypassed through Bash, and the "model cannot write approved" claim is false
```
[ -f "$pending" ] || hook_allow
```
The PreToolUse matcher is only `Edit|Write|MultiEdit`. The model can run `sed -i`, `tee` or `>` through Bash to edit the files directly. It can also write `~/.agent/review-address/approved` itself, or delete `pending`. The comment "the model cannot write `approved` itself" holds only for the Edit and Write tools. The blast radius is every session that runs `crew review address`.
Fix: either extend the gate to Bash and deny commands that touch `~/.agent/review-address` or write files while pending, or document the gate as a guardrail and not a boundary. The first option is preferable.

3. [attention · 4] **`.claude/hooks/review-address-approval.sh:19`** (answer handling) — `none` and free-form answers leave the session locked
```
# `none` authorizes no edit, so it records nothing
if printf '%s' "$prompt" | grep -Eqi '^[[:space:]]*(all|yes|ok|...
```
After `none`, `pending` stays and `approved` is never written, so every Edit and Write in the session is denied until it ends. The deny message tells the user to reply `none`, which is exactly the reply that cannot unlock. Natural answers such as "apply 1 and 3" or "all except 2" don't match the regex. They also leave the session locked. Numbered answers approve every edit, so the fix set is not enforced. The gate only checks that some approval exists.
Fix: on `none`, delete `pending` (or write a `resolved` state). Reject or ask again for unparsed answers. Store the parsed fix set in `approved`, and clear `pending` once the fixes are applied.

4. [attention · 3] **`.claude/hooks/review-address-gate.sh:12`** (state location) — one global marker pair is shared by all sessions
```
state="$HOME/.agent/review-address"
pending="$state/pending"
```
Concurrent Claude sessions overwrite each other's `pending` and `approved` files. If session B writes `pending`, session A's gate allows edits because the session no longer matches, so A's table is unguarded. A crashed session leaves an orphan `pending` forever. The session id is already available, so keying the files by it would remove the collision.
Fix: use `$state/$session/pending` and `$state/$session/approved`. Prune old directories on install.

5. [needs more info · 2] **`.claude/hooks/review-address-gate.sh:11`** (`lib/hook.sh`) — the gate may fail open if the sourced library is missing or wrong
```
. "$(dirname "$0")/lib/hook.sh"
```
`lib/hook.sh` is not in the package. If install does not copy it to `$HOME/.claude/hooks/lib/`, `set -e` aborts the script with a non-2 exit code. Claude Code treats that as a non-blocking error, so edits go through with no gate. Does the install step copy `lib/hook.sh`, and does `hook_deny` exit with code 2 or emit the JSON deny? If not, the gate silently does nothing, which is the failure this change set out to prevent.