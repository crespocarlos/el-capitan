Assessment: request-changes — a crashed or abandoned builder leaves a lock that blocks the user's own checkout, switch, restore and reset for up to 6 hours. The deny message doesn't say how to clear it.

Read beyond the package: `.agent/tools/task/task_lock.py`

Criteria: 0 satisfied, 0 partially satisfied, 0 contradicted, 4 unverified (no spec in context; the stated behaviour is the only criterion).

1. [attention · 4] **`.claude/hooks/guard/worker-tree.sh:44`** — deny message gives no way out when the builder is dead
```
hook_deny "The builder for task ${task:-unknown} holds $root. Do not change its branch or files from outside; wait for it, or run git -C against another tree."
```
Suppose a builder crashes, is killed, or its session is abandoned before it removes the lock. The tree is the user's main checkout. The user then can't run `git checkout`, `switch`, `restore` or `reset --hard` for up to 6 hours. The message says only "wait for it". It doesn't say how old the lock is, that it may be orphaned, or that `crew-progress.py lock remove <tree>` clears it. Nothing marks the lock as live, so a dead builder looks the same as a working one.
Fix: put the lock's age and the exact recovery command in the message, e.g. "If the builder is gone, run `crew-progress.py lock remove <root>` or delete `<root>/.crew-worker.lock`."

2. [attention · 3] **`.claude/hooks/guard/worker-tree.sh:41`** — a bare `CREW_WORKER_TASK=<id>` prefix bypasses the guard
```
if [[ $cmd =~ $inline ]]; then who=${BASH_REMATCH[2]}; fi
if [ -n "$who" ] && [ "$who" = "$task" ]; then hook_allow; fi
```
Any actor that knows the task id can bypass the guard, because the id is printed in the deny message. A user's agent that is told "denied" can read the id from that message and retry with the prefix. Then it changes the live builder's tree anyway. The message even names the id.
Fix: don't print the task id in the deny message, or accept that the exemption is advisory and document it in the message and header.

3. [nit · 3] **`.claude/hooks/guard/worker-tree.sh:38`** — a lock with a malformed `started` is silently ignored
A lock with a missing or non-numeric `started` gets `hook_allow` with no warning. If the lock is corrupted, the guard silently stops protecting the builder's tree. The cost is that nobody learns the protection is off.
Fix: emit a stderr note when the lock exists but can't be parsed.