Assessment: request-changes — the hook approach fits the problem, but the gate can lock up, can be re-armed with a stale approval, and doesn't cover Bash edits, so it doesn't yet enforce the gate.

Read beyond the package: none. The tree holds only the three changed files. `hooks/lib/hook.sh` and the skill that writes `pending` are not present, so I could not check them.

Approach: endorse — a PreToolUse hook plus a UserPromptSubmit hook is the harness's own way to enforce a gate that prose could not hold, and it beats adding new machinery.
Alternatives considered:
- Prose-only gate in the skill — this was tried and failed, so it loses.
- Return `permissionDecision: "ask"` from the PreToolUse hook while `pending` exists. It needs no approval hook, no regex and no `approved` marker. It loses on selecting fixes by number, but it is the cheaper design if the owner accepts a per-edit native prompt.
- Have the skill pass the approved fix numbers in the marker, and have the gate enforce them. This costs more, but it matches "which fixes to apply". The current design approves every edit once any answer is accepted.

1. [blocking · 4] **`.claude/hooks/review-address-approval.sh:19`** — `none`, or any unmatched reply, leaves the session locked out of every Edit and Write
```
# `none` authorizes no edit, so it records nothing; any other accepted answer authorizes at least one fix.
if printf '%s' "$prompt" | grep -Eqi '^[[:space:]]*(all|yes|...
```
The owner replies `none`, or something the regex doesn't match, such as "1 and 3" or "fix 2". Nothing is recorded and `pending` stays. The gate then denies all Edit and Write in that session, including unrelated edits. Nothing in the diff clears `pending`. The deny message also tells the user to reply "none", which can never unlock anything.
Fix: have the approval hook delete `pending` on `none`, and on any decline. Accept "1 and 3" style answers or tell the user the exact grammar. Also have the skill clear `pending` when it finishes.

2. [attention · 4] **`.claude/hooks/review-address-gate.sh:24`** — a stale `approved` marker satisfies a re-presented table
```
if [ -f "$approved" ]; then
  [ "$(jq -r '.session // empty' "$approved")" = "$session" ] \
    && [ "$(jq -r '.review_dir // empty' "$approved")" = "$armed_review" ] && hook_allow
```
The owner approves round 1 of review dir R. Later in the same session the skill re-runs on R, for example after a re-review, and writes a new `pending`. The old `approved` still matches on session and review_dir, so edits are allowed without a new answer. The marker carries no nonce or timestamp tying it to one table.
Fix: the skill removes `approved` when it writes `pending`, or `pending` carries an id that `approved` must echo.

3. [attention · 4] **`.claude/hooks/review-address-gate.sh:15`** — `pending` and `approved` are single global files, so concurrent sessions disarm each other
```
pending="$state/pending"
approved="$state/approved"
[ -f "$pending" ] || hook_allow
```
Session A presents a table. Session B, on another review, presents its own and overwrites `pending`. A's gate now reads a foreign session id and allows every edit. The gate fails open without any signal.
Fix: key the markers by session, for example `$state/$session.pending` and `$state/$session.approved`. This also removes the session comparisons.

4. [attention · 4] **`.claude/settings.json:20`** — the gate matches only `Edit|Write|MultiEdit`, so Bash can bypass it
```
"matcher": "Edit|Write|MultiEdit",
```
After the table is shown and before any approval, the model can run `sed -i` or `tee` through Bash, or use NotebookEdit. Neither is denied, so "structural" enforcement is only partial.
Fix: widen the matcher to `Edit|Write|MultiEdit|NotebookEdit|Bash`. For Bash, deny while the marker is pending and unapproved, or accept the gap and say so in the skill.

5. [attention · 3] **`.claude/hooks/review-address-gate.sh:18`** — the gate fails open on a missing `jq` or a corrupt marker
```
armed_session=$(jq -r '.session // empty' "$pending" 2>/dev/null || true)
[ -n "$session" ] && [ "$armed_session" = "$session" ] || hook_allow
```
If `jq` is absent or `pending` is malformed, `armed_session` is empty and the gate allows. The `approved` check at line 23 has no `|| true`, so under `set -e` a corrupt `approved` file exits non-zero, which Claude Code treats as a non-blocking error, so the edit proceeds. An enforcement gate failing open is silent.
Fix: if `pending` exists but cannot be parsed, deny, or at least log to stderr.

6. [needs more info · 2] **`.claude/settings.json:21`** — hook script paths and the `lib/hook.sh` dependency
The gate sources `$(dirname "$0")/lib/hook.sh`. The settings entry runs `$HOME/.claude/hooks/review-address-gate.sh`, and the other hook lives under `hooks/guard/`. Does install copy `.claude/hooks/*.sh` and `lib/` into each config dir? If it copies only `guard/`, or the config dir isn't `$HOME/.claude`, the `source` fails and the gate never arms. The skill that writes `pending` is also not in this change, so the marker schema `{session, review_dir}` has no tested contract with it.