Assessment: request-changes — a crashed or abandoned builder leaves the user's main checkout locked for up to 6 hours, and the deny message gives no way out.

1. [blocking · 4] **`.claude/hooks/guard/worker-tree.sh:44`** — A deny with no recovery path traps the user in their own checkout
```
hook_deny "The builder for task ${task:-unknown} holds $root. Do not change its branch or files from outside; wait for it, or run git -C against another tree."
```
The builder removes the lock as its last step, so a crash, kill, or abandoned session leaves a fresh lock behind. The user then can't run `checkout`, `switch`, `restore` or `reset --hard` in their main checkout for up to 6 hours. The message offers only "wait for it" or "use another tree". It doesn't say the lock is a file, where it is, or that deleting it clears the block. `task_lock.py` has `lock remove <tree>`, but nothing points the user to it. The person least able to tell a live builder from a dead one is the person being blocked. Fix: name the lock path and the age in the message. Add the recovery command, for example "If the builder is no longer running: `crew-progress.py lock remove $root`". Consider checking for a live builder (a pid in the lock) so a dead one stops denying early.

2. [attention · 3] **`.claude/hooks/guard/worker-tree.sh:43`** — The message doesn't say how long the block lasts
```
if [ $(( $(date +%s) - started )) -lt "$STALE_SECONDS" ]; then
  hook_deny "The builder for task ${task:-unknown} holds $root. ...
```
"Wait for it" gives no time frame. The hook already has `started`, so it could report how long ago the builder started and when the lock expires. Without that, the user can't tell a 5-minute wait from a 6-hour one, and can't judge whether the builder is stuck. Fix: add "started N min ago; the lock expires in M min" to the deny text.

3. [needs more info · 2] **`.claude/hooks/guard/worker-tree.sh:7`** — Builders that run longer than 6 hours lose protection
The lock goes stale at 6 hours whether or not the builder is alive. A long-running builder then loses its protection, and a user checkout could silently change the files it is working on. Is a 6-hour cap an accepted maximum builder runtime? If builders can exceed it, the guard fails exactly when a build is long and the user is most likely to get impatient. The same question applies to refreshing the lock's `started` value while the builder is alive.