Assessment: request-changes — a crashed or killed builder leaves a lock that blocks the user from `checkout`, `switch`, `restore` and `reset --hard` in their own checkout for up to 6 hours, and the deny message gives no way to clear it.

Read beyond the package: `.agent/tools/task/task_lock.py`

Criteria: no spec was provided, so none were walked. The change description names these behaviours:
- The orchestrator writes the lock at dispatch. Unverified: only the hook and `remove_lock` are in the tree.
- The hook denies the four git commands while the lock is fresh. Satisfied.
- The builder is exempt. Partially satisfied (see finding 2).
- The builder removes the lock as its last step. Unverified.

1. [blocking · 4] **`.claude/hooks/guard/worker-tree.sh:44`** — A stale-but-fresh lock from a dead builder traps the user, and the message offers no recovery
```
hook_deny "The builder for task ${task:-unknown} holds $root. Do not change its branch or files from outside; wait for it, or run git -C against another tree."
```
The person here is the owner of the checkout. If the builder crashes, is killed or is interrupted, the lock is never removed. For up to 6 hours the owner can't switch branches, restore a file or reset in their own repo. The message says "wait for it", but no builder is running, so the wait is pointless. It doesn't mention `crew-progress.py lock remove <tree>`, or that the lock expires on its own after 6 hours. It also doesn't say whether the builder is still alive. "Run git -C against another tree" doesn't help someone with one checkout. The lock records no PID or heartbeat, so nothing separates a live builder from a dead one.
Fix: put the recovery command and the expiry time in the deny message, for example "If no builder is running, clear it with `crew-progress.py lock remove <root>` (the lock expires at <time>)". Ideally also record a PID in the lock and treat the lock as stale when that process is gone.

2. [attention · 3] **`.claude/hooks/guard/worker-tree.sh:41`** — The exemption is an honour system, and the deny message doesn't name it
```
inline='(^|[[:space:];&|])CREW_WORKER_TASK=["'"'"']?([^[:space:]"'"'"';&|]*)'
if [[ $cmd =~ $inline ]]; then who=${BASH_REMATCH[2]}; fi
```
Any command can set `CREW_WORKER_TASK=<task>` inline and bypass the guard. The user can do this too, but the deny message never says so. A builder that doesn't have the variable in its hook environment is denied in its own tree, and nothing tells it why. A denied builder is stuck mid-task and may retry or give up.
Fix: add the override to the deny message, or state which variable the builder must set.

3. [attention · 3] **`.claude/hooks/guard/worker-tree.sh:19`** — The guard is bypassed, with no signal, in common command forms
```
INSPECT=$(printf '%s' "$cmd" | sed -E "s/'[^']*'/''/g; s/\"[^\"]*\"/\"\"/g")
grep -Eq -- "$CHANGES_TREE" <<<"$INSPECT" || hook_allow
```
Quoted text is blanked. A command like `bash -c "git checkout x"` or `sh -c 'git reset --hard'` is allowed. So is `git --git-dir=... checkout`. `git reset --hard` is only matched with a single space after `reset`. Other forms of the same destructive change, such as `git stash`, `git clean -fd` and `git checkout`-equivalent `git restore`, get through or are not covered. The header comment admits "best effort", but the user then believes the tree is protected when it isn't.
Fix: also inspect the text inside `-c` quotes, or document the limits in the deny and help text.

4. [nit · 3] **`.claude/hooks/guard/worker-tree.sh:36`** — A lock with a bad `started` value fails open silently
```
case "$started" in '' | *[!0-9]*) hook_allow ;; esac
```
A lock with a malformed `started` line, for example one cut short by a partial write, protects nothing, and nobody is told. The cost is low, but the failure is invisible to both the builder and the user.