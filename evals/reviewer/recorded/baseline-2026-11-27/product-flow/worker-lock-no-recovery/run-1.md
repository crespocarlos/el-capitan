Assessment: request-changes — a builder that crashes or is killed leaves a lock that blocks the user's own checkout for up to 6 hours. The deny message gives no way out.

1. [attention · 4] **`.claude/hooks/guard/worker-tree.sh:44`** — Deny message has no recovery path for a dead builder
```
hook_deny "The builder for task ${task:-unknown} holds $root. Do not change its branch or files from outside; wait for it, or run git -C against another tree."
```
The builder removes the lock only as its last step. If it crashes, is killed, or the session dies, the lock stays and the user is denied `checkout`, `switch`, `restore` and `reset --hard` in their own main checkout for up to 6 hours. The message tells them to wait or use another tree. It doesn't say how to tell a live builder from a dead one, how old the lock is, or that `crew-progress.py lock remove <tree>` clears it. Neither does `task_lock.py`'s docstring. The user ends up stuck, and the likely workaround is to `rm` the file by hand, or to disable the hook. Tell them they can remove it, so the guard isn't also a trap.
Fix: Include the lock's age and the exact recovery command in the deny text. For example: "Started ${age} ago. If that builder is dead, run `crew-progress.py lock remove $root`, or delete $root/.crew-worker.lock."

2. [attention · 3] **`.claude/hooks/guard/worker-tree.sh:11`** — Fixed 6-hour expiry fits neither dead nor long-running builders
```
STALE_SECONDS=21600
```
A crashed builder blocks the user for hours. A builder that runs longer than 6 hours loses its protection mid-task, so the user can then check out underneath it. There is no heartbeat or liveness check, such as a PID or a refreshed timestamp. Lock freshness is the only signal.
Fix: Have the builder refresh `started` periodically, or record its PID in the lock and treat a lock whose process is gone as stale.

3. [nit · 3] **`.claude/hooks/guard/worker-tree.sh:36`** — A malformed lock fails open without telling the user
```
case "$started" in '' | *[!0-9]*) hook_allow ;; esac
```
A corrupt or partial lock silently stops protecting the tree. The user sees nothing, and a live builder's files can be reset. This is the safer failure direction for the user, but it is invisible.
Fix: Allow the command, and emit a warning that the lock is unreadable.