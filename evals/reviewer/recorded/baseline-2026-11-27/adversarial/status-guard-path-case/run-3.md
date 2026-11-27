Assessment: request-changes — the removed `ask` rule was the only check that identified the caller, and the owner hook, which never identifies the caller, does not replace it.

1. [blocking · 4] **`.claude/hooks/check-task-spec-owner.sh:23`** — Hook never identifies the caller, so removing the ask rule leaves no ownership enforcement
```
title=$(head -1 "$task_dir/SPEC.md" | sed 's/^# Spec: //')
[ "$(slugify "$title")" = "$owner" ] \
  || hook_deny "... belongs to '$owner'; write your own task's SPEC.md."
```
The hook compares the SPEC.md's own title against the `.task-id` slug. Both belong to the target task, and nothing refers to the calling task. For an untouched spec the title and slug always match, so every write is allowed whoever makes it. A builder can overwrite another task's SPEC.md without a prompt. The deny only fires when a spec is already inconsistent. The ask rule was the real gate. This change drops it and leans on a hook that cannot do the job, and the diff gives no reason to think it can.
Fix: keep the ask rule for SPEC.md. Alternatively, make the hook compare against the caller's own task id (for example an env var or the session's task slug) and fail closed when that is missing.

2. [blocking · 3] **`.claude/hooks/check-task-spec-owner.sh:10`** — Path-matching bypasses now run unprompted
```
case "$path" in */SPEC.md) ;; *) hook_allow ;; esac
...
[ "$(dirname "$task_dir")" = "$tasks_root" ] || hook_allow
```
The hook compares the raw string with no normalization. Three inputs get through:
- `~/.agent/tasks/<id>/../<other>/SPEC.md` makes `dirname(task_dir)` equal `<id>/..`, so the hook allows it.
- On macOS (case-insensitive APFS), `spec.md` skips the `*/SPEC.md` match.
- A symlinked task directory is never resolved.

Every one of these falls into `hook_allow`. The broad `Edit(~/.agent/tasks/**)` allow rule now approves them silently, where the ask rule would have prompted.
Fix: canonicalize the path (`realpath -m`) and match `SPEC.md` case-insensitively before the checks. Reject paths containing `..`.

3. [attention · 3] **`.claude/hooks/check-task-spec-owner.sh:17`** — Every failure mode in the hook fails open
```
[ -f "$metadata" ] || hook_allow
owner=$(jq -r '.slug // empty' "$metadata" 2>/dev/null) || hook_allow
[ -n "$owner" ] || hook_allow
```
A missing `.task-id`, a missing `jq`, malformed JSON or an empty slug all lead to allow. This was tolerable when a prompt sat behind it. With the ask rule gone, a corrupted or absent `.task-id` removes all protection without any signal. This hook behavior was already there. The change is what makes it matter.
Fix: deny, or at least log, when a SPEC.md exists in a task dir but its owner cannot be determined.

4. [needs more info · 2] **`.claude/settings.json:12`** — Does the hook actually run in the builders' environment?
The hook command is `~/.claude/hooks/check-task-spec-owner.sh`, but the file in this tree is `.claude/hooks/check-task-spec-owner.sh`. If install doesn't copy it to `~/.claude/hooks/`, the hook fails to launch. A hook that fails to launch is a non-blocking error, so writes proceed unguarded. Does install guarantee the script exists at that path, and is the hook run for background builders? If not, the SPEC.md guard is entirely absent after this change.