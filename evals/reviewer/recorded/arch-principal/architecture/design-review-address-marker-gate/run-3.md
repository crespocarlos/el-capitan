Assessment: request-changes — the marker design is sound, but the approval is never invalidated or cleared, "none" leaves the session locked, and Bash edits bypass the gate.

Read beyond the package: none. The working directory holds only the three changed files, and `lib/hook.sh` is not among them. I made 2 tool calls.

Approach: redirect — keep the two-hook structure, but make the markers per-session and single-use, and cover every write path.
Alternatives considered:
- Prose in the skill — this already failed to hold the gate, so the structural gate wins.
- Skill-only state with no hooks (the skill asks via `AskUserQuestion`) — this is cheaper, but the model could still skip the call, so it enforces nothing.
- One PreToolUse hook that reads the transcript for the last user message — it needs no approval marker and so no stale state. It depends on the transcript format and is harder to test, so it loses narrowly. It deserves a look if the markers keep producing edge cases.
- Permission-mode `ask` for Edit/Write while pending — this uses the platform's own prompt, which is the "use what exists" option. Its limit is that it approves per tool call, not per fix set, so the markers win on fidelity.

1. [attention · 4] **`.claude/hooks/review-address-gate.sh:23`** — an old `approved` marker satisfies a new `pending`
```
if [ -f "$approved" ]; then
  [ "$(jq -r '.session // empty' "$approved")" = "$session" ] \
    && [ "$(jq -r '.review_dir // empty' "$approved")" = "$armed_review" ] && hook_allow
```
The gate matches `approved` only on session and review directory. Nothing deletes `approved` or ties it to a particular `pending`. A second `crew review address` run in the same session on the same review directory rewrites `pending`, and the first round's `approved` still matches. Edits are then allowed before the owner answers the new table. Nothing clears either marker when the work finishes, so the session stays gated or ungated indefinitely.
Fix: put a nonce or timestamp in `pending` and copy it into `approved`. The gate compares the nonce. The skill deletes both markers when the address run ends.

2. [attention · 4] **`.claude/hooks/review-address-approval.sh:18`** — a "none" reply leaves the session locked, and the approval is not tied to the fix set
```
# `none` authorizes no edit, so it records nothing
if printf '%s' "$prompt" | grep -Eqi '^[[:space:]]*(all|yes|ok|...
```
After the owner answers "none", `pending` stays and `approved` is never written. Every Edit or Write in that session is then denied with "Reply with the fixes to apply", and the message tells the owner nothing useful. Any later bare "ok" or "yes" aimed at something else is also recorded as approval. The marker stores the prompt, but the gate never checks which fixes were approved.
Fix: on "none", delete `pending`. Only consume an approval that arrives after the table was presented, with the nonce from finding 1. Have the skill read `approved.prompt` for the fix set.

3. [attention · 4] **`.claude/settings.json:20`** — the matcher covers only the Edit, Write and MultiEdit tools
```
"matcher": "Edit|Write|MultiEdit",
```
The requirement is that nothing is edited before the owner answers. While `pending` exists, the model can still change files through Bash (`sed -i`, `tee`, `cat >`) or NotebookEdit. The gate does not see those calls.
Fix: add `Bash` and `NotebookEdit` to the matcher. For Bash, deny when pending is unapproved and the command is not read-only, or state plainly that the gate covers only the file tools.

4. [attention · 3] **`.claude/hooks/review-address-gate.sh:19`** — the gate fails open when the session id is unreadable
```
[ -n "$session" ] && [ "$armed_session" = "$session" ] || hook_allow
```
An empty `session_id` allows the edit. So does any `jq` failure on `pending`, since `|| true` turns it into an empty value. A corrupt or half-written marker disables the gate with no signal. `pending` is also one global file, so two concurrent sessions overwrite each other's markers.
Fix: write markers at `$state/<session_id>/{pending,approved}`. Deny, or log loudly, when `pending` exists but cannot be parsed.

5. [needs more info · 3] **`.claude/hooks/review-address-gate.sh:9`** — `lib/hook.sh` is not in the package
```
. "$(dirname "$0")/lib/hook.sh"
```
Settings run the script from `$HOME/.claude/hooks/`, so `lib/hook.sh` must be installed next to it. It is not in the working directory, and I could not confirm that the helper defines `hook_field`, `hook_allow` and `hook_deny`, or that install copies it. If the source fails under `set -e`, the hook exits non-zero. Claude Code treats that as a non-blocking error, so the edit goes through and the gate silently stops working. Does install ship `lib/hook.sh` into each config dir, and does a test cover a deny end to end?