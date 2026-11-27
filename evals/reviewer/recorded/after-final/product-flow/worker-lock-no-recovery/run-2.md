Persona: the operator (or an agent) working in their own main checkout while a builder is running.

Assessment: request-changes — a crashed or killed builder leaves a lock that blocks the operator's checkout for up to 6 hours. The deny message offers no way out except `git -C` against another tree.

Read beyond the package: `.agent/tools/task/task_lock.py`; a grep for the lock name found no other consumer.

Criteria: 0 satisfied, 0 partially satisfied, 0 contradicted, 4 unverified. No spec was in context. The four I walked were: guard hook, exemption for the builder, removal at exit, and a stale lock.

1. [blocking · 4] **`.claude/hooks/guard/worker-tree.sh:44`** (h1) — a crashed builder strands the operator in their own checkout for up to 6 hours
```
hook_deny "The builder for task ${task:-unknown} holds $root. Do not change its branch or files from outside; wait for it, or run git -C against another tree."
```
The builder removes the lock only as its last step. If it is killed, crashes, or the session is closed, the lock stays. The operator then cannot run `git checkout`, `switch`, `restore` or `reset --hard` in their main checkout, including to discard the builder's half-done edits. The message says "wait for it", but nothing is running. It does not say how to tell whether the builder is alive, and it never names `lock remove`. `git -C <other tree>` does not help when the main checkout is the tree that is locked. The only exits are a 6-hour wait or manually deleting a hidden file the message never mentions.
Fix: Name the recovery in the deny message: "If the builder is dead, run `crew-progress.py lock remove <root>` (or delete `<root>/.crew-worker.lock`)". Also show the lock's age and `started_at` in the message. Better still, record the builder's pid in the lock and treat the lock as stale when that pid is gone.

2. [attention · 3] **`.claude/hooks/guard/worker-tree.sh:41`** — a refusal with no stale-lock path and no confirmation
```
if [ -n "$who" ] && [ "$who" = "$task" ]; then hook_allow; fi
```
The exemption relies on the builder passing `CREW_WORKER_TASK` through its environment or as an inline prefix. A builder whose shell does not carry that variable, for example after a restart, would be denied in its own tree. Its denial message then tells it to "wait for it", which is itself. The message also does not tell a builder to set the variable.
Fix: Add to the deny text: "If you are this builder, set CREW_WORKER_TASK=<id>".

3. [nit · 3] **`.claude/hooks/guard/worker-tree.sh:15`** — the deny covers only four git forms
Forms like `git stash`, `git clean -fd`, `git checkout` via an alias, or `git reset --keep` pass without a message. The header comment says "best effort", but an operator may still believe the tree is protected. Cost: false confidence. Fix: state the covered commands in the deny message, or in the docs.