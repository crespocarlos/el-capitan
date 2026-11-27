Assessment: request-changes — a crashed or abandoned builder leaves the user locked out of checkout, switch, restore and reset --hard in their own checkout for up to 6 hours, and the denial message gives no way out.

1. [attention · 4] **`.claude/hooks/guard/worker-tree.sh:45`** — the deny message offers no recovery path for a dead builder
```
hook_deny "The builder for task ${task:-unknown} holds $root. Do not change its branch or files from outside; wait for it, or run git -C against another tree."
```
Only the builder removes the lock, as its last step. If the builder crashes, is killed, or the session ends, the lock stays. The user's main checkout then rejects `checkout`, `switch`, `restore` and `reset --hard` for up to 6 hours. The message says "wait for it", which is wrong when no builder is running. It does not give the lock age, the time it goes stale, or the `crew-progress.py lock remove <tree>` command. The only other advice is `git -C` against another tree, which doesn't help someone working in their main checkout. The user can't tell a live builder from a dead one, and may not find out that deleting the lock is safe.
Fix: Put the lock age and expiry time in the message. Name the release command: "If no builder is running, release it with `crew-progress.py lock remove <root>` or delete `$root/.crew-worker.lock`."

2. [attention · 3] **`.claude/hooks/guard/worker-tree.sh:40`** — a fixed 6-hour window with no liveness check blocks the user's recovery commands
```
if [ $(( $(date +%s) - started )) -lt "$STALE_SECONDS" ]; then
```
The user's usual way to clean up after a failed builder is `git restore` or `git reset --hard`. Those are the commands this hook blocks. A failed run leaves a half-changed tree, and the guard stops the person from fixing it until the lock expires or they find and delete the file themselves. The lock records no builder PID or heartbeat, so the hook can't tell a dead builder from a live one.
Fix: Have the builder refresh a heartbeat and use a short staleness window based on it. Or record the PID and allow the command when that process is gone.

3. [nit · 3] **`.claude/hooks/guard/worker-tree.sh:6`** — the builder exemption depends on an inline env prefix the user never sees
The builder is exempt only through `CREW_WORKER_TASK`, which the hook sees in its own environment or as an inline prefix. If the builder's harness doesn't pass that variable to the hook, the builder gets blocked by its own lock. The failure shows up as the same "Do not change its branch" message, which is confusing for the builder. The message could mention `CREW_WORKER_TASK` so the builder can diagnose it.