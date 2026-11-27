Assessment: request-changes — the gate is the right structural fix, but the marker lifecycle is incomplete. `pending` is never cleared, `approved` is never invalidated, and the claim that the model can't write `approved` doesn't hold.

Read beyond the package: none. The working directory holds only the three changed files, so `lib/hook.sh`, the skill, and the installer are not visible.

Approach: redirect — keep the hook-based gate, but give the markers a lifecycle: one state file per session, a nonce per presented table, and a clear step when the review ends.
Alternatives considered:
- Keep the prose gate in the skill — loses, because it already failed. A hook is the correct layer.
- A single state file written by the skill and advanced only by the hook (`pending` → `approved` or `declined`, keyed by session and a table nonce) — wins. It removes the stale-approval and stuck-deny cases below and has one owner for the state.
- Make the prompt hook itself run the apply step, or rely on Claude Code's built-in permission prompt for Edit/Write — partly viable, but it loses the "owner picks which fixes" semantics.

1. [attention · 4] **`.claude/hooks/review-address-gate.sh:22`** — `approved` is never invalidated, so a second table in the same session is already approved
```
if [ -f "$approved" ]; then
  [ "$(jq -r '.session // empty' "$approved")" = "$session" ] \
    && [ "$(jq -r '.review_dir // empty' "$approved")" = "$armed_review" ] && hook_allow
```
The owner approves round 1 for a review directory. The skill is then re-run on the same directory, or the table is re-presented after a re-review, and it overwrites `pending` with identical session and review_dir. The old `approved` still matches, so edits are allowed with no new approval. This is the failure the change exists to prevent. Nothing in the diff removes `approved` when `pending` is written, and the keys don't include a table identity.
Fix: add a nonce or timestamp to `pending` and copy it into `approved`. The gate should require them to match. Alternatively, have the skill delete `approved` when it writes `pending`.

2. [attention · 4] **`.claude/hooks/review-address-approval.sh:19`** — "none" and "done" are never recorded, so edits stay denied for the whole session
```
# `none` authorizes no edit, so it records nothing
```
The owner answers "none". `pending` stays and `approved` is never written. Every later Edit/Write in that session, including unrelated work, is denied with "has no approval yet. Reply with the fixes to apply". After an "all" the opposite happens: `pending` and `approved` remain, so the gate is permanently open for that review directory. No component clears `pending`, so the gate has no end state.
Fix: have the approval hook record `declined`, or delete `pending`, on "none". Have the skill or a Stop hook remove both markers when the apply step finishes.

3. [attention · 3] **`.claude/hooks/review-address-approval.sh:19`** — any bare "ok" or number after `pending` is treated as approval
```
grep -Eqi '^[[:space:]]*(all|yes|ok|...)[[:space:].!]*$|^...[0-9]+(...)*$'
```
Between the table and the owner's real answer, the owner may reply "ok" or "2" to a clarifying question from the model. The hook records that as approval and the gate opens. The stored `prompt` is not checked against the table's finding numbers, so "99" approves too.
Fix: accept an answer only if it is the first user prompt after `pending` was written. Also validate numbers against the count of findings in the table.

4. [attention · 3] **`.claude/hooks/review-address-approval.sh:3`** — the claim "the model cannot write `approved` itself" is false, because the gate only covers Edit|Write|MultiEdit
```
"matcher": "Edit|Write|MultiEdit"
```
The model can run `echo '{...}' > ~/.agent/review-address/approved`, or `sed -i` on source files, through Bash. Neither goes through the gate. The comment overstates what is enforced, and the "structural" guarantee covers only the model's cooperative path.
Fix: add Bash to the gate's matcher with a narrow rule that denies writes to `~/.agent/review-address`. Alternatively, reword the comment and docs to say this is a guardrail, not a security boundary.

5. [needs more info · 2] **`.claude/settings.json:21`** — will `lib/hook.sh` and the two scripts reach `$HOME/.claude/hooks/`?
The gate sources `lib/hook.sh`, and the settings point at `$HOME/.claude/hooks/review-address-*.sh`. I couldn't see the installer or `lib/hook.sh`. If install copies only `guard/` or the scripts without `lib/`, the gate fails at source time. With `set -e` that is a nonzero exit, which Claude Code treats as a non-blocking error, so the gate silently fails open. Question: does install copy `lib/` and these scripts, and does a missing `lib/hook.sh` fail closed? If not, the gate does nothing on installed machines.

### Findings: 5