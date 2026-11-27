Assessment: approve — hooks are the right layer, since a PreToolUse deny plus a user-turn-only approval is a structural gate and prose was not. The marker protocol has gaps, listed below.
Read beyond the package: none. The working directory holds only the three changed files. `lib/hook.sh`, the skill and the install merge are not present, so I could not read them.

Approach: endorse — a hook-enforced pending/approved handshake is the smallest mechanism that makes the gate structural. It beats strengthening the skill prose, which already failed, and a custom CLI wrapper around edits, which can't intercept the tools the model calls directly.
Alternatives considered:
- Keep the gate in skill prose and strengthen the wording — loses, because the prose already failed to hold the gate.
- Use Claude Code's built-in permission prompt (`ask` rules for Edit/Write while review-address runs) — it is simpler and has no marker files. It loses because it cannot tie the approval to the verdict table or to the owner's reply format. It is worth keeping as a fallback layer.
- A single session-scoped state file keyed by session id and review dir, written by the skill and cleared on completion — this is the same design with fewer ways to go wrong. See findings 1 and 2.

1. [attention · 4] **`.claude/hooks/review-address-gate.sh:22`** — A stale `approved` marker re-opens the gate for the same review directory
```
if [ -f "$approved" ]; then
  [ "$(jq -r '.session // empty' "$approved")" = "$session" ] \
    && [ "$(jq -r '.review_dir // empty' "$approved")" = "$armed_review" ] && hook_allow
```
Nothing clears `approved`, and a match needs only session and review dir. Suppose the owner approves the table, then the skill re-presents a table for the same review dir after a re-review or another round in the same session. The skill writes a new `pending`, but the old `approved` still matches, so edits are allowed with no new approval. The gate fails open exactly where the change is meant to hold.
Fix: have the skill put a nonce or timestamp in `pending`. The approval hook copies it into `approved`, and the gate compares it. Also have the skill delete `approved` whenever it writes `pending`.

2. [attention · 4] **`.claude/hooks/review-address-approval.sh:4`** — One global marker pair for all sessions, with no cleanup
```
state="$HOME/.agent/review-address"
pending="$state/pending"
approved="$state/approved"
```
The comments call the markers "scoped to a session", but each is a single file. Two Claude sessions running `address` at once overwrite each other's `pending`. The first session's gate then silently allows its edits, because `armed_session` no longer matches. After the owner replies `none`, nothing is recorded and `pending` stays. Every later Edit in that session is denied with a message that tells the owner to pick fixes from a table they already declined. Nothing ever removes `pending`.
Fix: key the files by session, for example `$state/$session/pending`. Have the gate clear or ignore `pending` after `none` and when the skill finishes. Record `none` as an explicit `declined` state that the gate handles separately.

3. [attention · 4] **`.claude/settings.json:19`** — The matcher misses other write paths, so the gate is not structural for them
```
"matcher": "Edit|Write|MultiEdit",
```
While the gate is armed, the model can still change files with `Bash` (`sed -i`, `tee`, `> file`, `git apply`) and with `NotebookEdit`. A model that wants to apply a fix before approval just takes one of these. The change presents the gate as structural, so this gap undercuts it.
Fix: add `Bash` and `NotebookEdit` to the matcher. While pending is unapproved, allow only read-only Bash commands, or deny Bash outright. Otherwise document that the gate covers the edit tools only.

4. [attention · 3] **`.claude/hooks/review-address-approval.sh:17`** — The approval is not bound to the fixes it selects
```
jq -n --arg s "$armed_session" --arg r "$armed_review" --arg p "$prompt" '{session:$s, review_dir:$r, prompt:$p}' > "$approved"
```
The reply `1` and the reply `all` produce the same effect, because the gate allows every edit in the session. After the owner approves fix 1, the model can edit for fixes 2 and 3 too. Whether the skill enforces the subset is not visible here. Replies like "1,3 but skip 2" do not match the regex, so they are denied. That is safe but leaves the owner with no way forward, and the deny message does not say so.
Fix: keep the numbers in `approved` so the skill can read them back, and say in the docs that the gate enforces "approved or not", not which fixes. Alternatively, have the deny message state which reply forms are accepted.

5. [needs more info] **`.claude/hooks/review-address-gate.sh:10`** — Sourced `lib/hook.sh` and the installed hook paths could not be checked
```
. "$(dirname "$0")/lib/hook.sh"
```
`settings.json` calls `$HOME/.claude/hooks/review-address-gate.sh`, but the repo copy is under `.claude/hooks`. I could not see `lib/hook.sh` or the install merge. If install does not copy the two scripts and `lib/` into each config dir, the hook command fails. The gate script then sources a missing lib and exits non-zero, which Claude Code treats as a non-blocking error, so the gate allows the edit. The approval hook always exits 0, so no one would notice the failure. Question: does install copy the hooks and `lib/hook.sh`, and does `hook_deny` emit the PreToolUse deny JSON or exit 2? If either is not true, the gate silently never fires.