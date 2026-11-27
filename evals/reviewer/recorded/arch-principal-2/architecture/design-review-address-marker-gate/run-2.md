Assessment: approve — a PreToolUse deny plus a UserPromptSubmit approval is the right structural fix for a gate that prose could not hold, though the bypass and fail-open gaps below weaken it.
Read beyond the package: none (the working directory holds only the three changed files; `lib/hook.sh` is absent)

Approach: endorse — a hook-enforced marker pair is the platform's own mechanism for a gate the model cannot talk its way past.
Alternatives considered:
- Keep the gate as skill prose and strengthen the wording — it already failed, and prose cannot stop a tool call, so the hook wins.
- A single `permissions.ask` or deny rule on Edit/Write while the skill runs — it needs no scripts, but it cannot tell an approved fix from an unapproved one and prompts on every edit. The hooks win by taking approval from the owner's own reply in the conversation.
- One hook that creates both markers — it loses because the model could trigger approval itself. Keeping the approval writer on UserPromptSubmit is the correct split.

1. [attention · 4] **`.claude/settings.json:18`** — Gate covers Edit/Write only, so Bash bypasses it
```
"matcher": "Edit|Write|MultiEdit",
```
While the table is pending, the model can run `sed -i`, `tee` or `cat > file` through Bash and edit without approval. It can also run `echo '{...}' > ~/.agent/review-address/approved` or `rm …/pending` to clear the gate. The comment "the model cannot write `approved` itself" is true only for the Write tool. The gate denies the model's own Write to `approved` but not a Bash redirect.
Fix: extend the matcher to `Bash` and deny, while a pending marker is unapproved, any command that mutates files or touches `~/.agent/review-address`. Alternatively narrow the claim in the comments to say what the gate does and does not stop.

2. [attention · 4] **`.claude/hooks/review-address-gate.sh:19`** — A single global `pending` file lets another session disarm the gate
```
[ -n "$session" ] && [ "$armed_session" = "$session" ] || hook_allow
```
`pending` and `approved` are one file each. If a second Claude session presents its own table, it overwrites `pending`, so the first session now sees a different session id and every edit is allowed. Session A has presented a table and is waiting. Session B writes `pending`. Session A's model then edits with no approval.
Fix: key the markers by session, for example `$state/pending-$session.json` and `$state/approved-$session.json`. Drop the cross-session comparison.

3. [attention · 3] **`.claude/hooks/review-address-gate.sh:10`** — A missing `lib/hook.sh` makes the gate fail open
```
set -euo pipefail
. "$(dirname "$0")/lib/hook.sh"
```
The diff does not add `lib/hook.sh`, and the settings point at `$HOME/.claude/hooks/review-address-gate.sh`. If install does not also copy `lib/`, the `source` fails and the script exits 1. A PreToolUse hook exiting 1 is a non-blocking error, so edits go through with no gate. A missing `jq` has the same effect, because `armed_session` comes back empty and the script takes the allow branch.
Fix: have install copy `lib/hook.sh` and verify it. In the gate, check for `jq` and the sourced file up front and exit 2 (deny) when a pending marker exists and the gate cannot evaluate it.

4. [attention · 3] **`.claude/hooks/review-address-approval.sh:21`** — A stale `approved` marker auto-approves a re-run on the same review directory
```
jq -n --arg s … '{session:$s, review_dir:$r, prompt:$p}' > "$approved"
```
Nothing clears `approved` when the skill writes a new `pending`. If the owner addresses review X, then re-presents a table for X in the same session (a second round after re-review), the old `approved` still matches on session and `review_dir`. The gate allows edits before the new reply. Add a nonce or timestamp to `pending` that `approved` must echo, or have the skill delete `approved` when it arms.
Fix: have the skill remove `approved` when it writes `pending`, or have `pending` carry an id that `approved` copies and the gate compares.

5. [nit · 3] **`.claude/hooks/review-address-approval.sh:17`** — The approval records no fix set, so a partial approval opens everything
A reply of `2` or `1,3` writes the same `approved` marker as `all`, and the gate then allows every edit. The recorded `prompt` field is never read. The owner who approves one fix has therefore authorized all of them, as far as the hook can tell. This is acceptable only if the skill is trusted to honor the numbers. Say so in the comment, or make the gate check the selection.