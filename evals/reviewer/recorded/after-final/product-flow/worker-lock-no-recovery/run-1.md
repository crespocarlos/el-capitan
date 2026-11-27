Assessment: request-changes — the deny message gives the user a stuck-lock case with no way out, and the lock stays "fresh" for up to 6 hours after a builder crashes.
Read beyond the package: .agent/tools/task/task_lock.py

The person affected is an operator in their main checkout, or an agent running there. A crashed or interrupted builder never reaches its last step, which is removing the lock. The operator then cannot run `checkout`, `switch`, `restore` or `reset --hard` in their own tree for up to 6 hours.

Criteria: 0 satisfied, 0 partially satisfied, 0 contradicted, 4 unverified (no spec in context).

1. [attention · 4] **`.claude/hooks/guard/worker-tree.sh:45`** — deny message has no recovery path for a dead builder
```
hook_deny "The builder for task ${task:-unknown} holds $root. Do not change its branch or files from outside; wait for it, or run git -C against another tree."
```
A builder that crashes, is killed or loses its session leaves the lock behind. The operator then sees "wait for it", but nothing is running, and the lock stays fresh for up to 6 hours. The message doesn't say when the lock started, when it expires, or how to clear it. The operator may hand-edit the lock or disable the hook. The unchanged `task_lock.py` documents `lock remove <tree>`, but the message never mentions it.
Fix: Include the lock's `started_at` and its expiry time. Name the command that clears it: `crew-progress.py lock remove <root>`. Add "if no builder is running, remove the lock".

2. [attention · 3] **`.claude/hooks/guard/worker-tree.sh:11`** — the operator can't tell a live lock from an orphan
```
STALE_SECONDS=21600
```
The only signal is the lock's age, with no heartbeat or PID. A builder that dies 5 minutes in blocks the tree for almost 6 hours. A builder that runs longer than 6 hours loses its protection mid-run. The hook also duplicates the constant from `task_lock.py`, so the two can drift apart.
Fix: Record the builder's PID or a refreshed timestamp in the lock and treat a dead PID as stale. Otherwise state the limitation in the deny message. Source the constant from one place.

3. [nit · 3] **`.claude/hooks/guard/worker-tree.sh:12`** — the deny text is vague about which tree is blocked
```
CHANGES_TREE="${GIT}(checkout|switch|restore|reset[[:space:]]+--hard)...
```
The hook blocks every `git restore`, including `restore --staged`, which doesn't touch files. It gives no hint that a read-only alternative such as `git -C` against another tree exists, beyond the closing clause. The operator is left guessing what is allowed.
Fix: Name the blocked verbs in the message and say which commands are still allowed.