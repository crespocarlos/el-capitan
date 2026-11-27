Assessment: request-changes — the hook records the PR on a branch match, but the minimal-task fallback can create duplicate DONE tasks and it doesn't cover `mark-done`/`mark-implementing` interplay, so it only handles the case someone hit.

Only the excerpt file exists. `append_pr`, `close`, `candidates`, `head`, `tasks_in`, `Pull` and `atomic_write` are not defined in the working directory, so I could not check their behavior. Claims that depend on them are marked as such.

1. [blocking · 4] **`.agent/tools/task/task_record_pr.py:42`** — A closed task whose PR was already recorded can pick up a second PR on the same branch

```python
chosen = [r for r in matches if head(r) not in CLOSED] or matches
...
done = "recorded PR" if append_pr(r.task, found.url) else "already has"
```

When the only match is a DONE or ABANDONED task, the `or matches` fallback appends the new PR to it. This is the case where a branch is reused for a second PR, or where `mark-done --pr-url` has already closed the task. The second PR is attached to an unrelated, finished task and no new task or notice appears. An ABANDONED task silently gaining a live PR is worse. The comment says "the single match", but a closed match isn't a reliable identity for the new PR.

Fix: for a closed-only match, append only if the URL is already recorded or the task has no PRs. Otherwise report a candidate, or create a new task.

2. [attention · 3] **`.agent/tools/task/task_record_pr.py:21`** — `minimal_task` has no idempotency or race guard

```python
directory = tasks_dir / str(uuid.uuid4()).upper()
directory.mkdir(parents=True)
```

Two hook invocations for the same PR, such as a retry or a concurrent `gh pr create` followed by a manual `record-pr`, both pass `place` with no match. Each then makes its own random-UUID directory, so `crew ls` shows duplicate DONE tasks. The first run's task is only found on a second call because it carries the same `branch`. That makes the duplicate come from the race, not from a missing match. There is also no lock around the read-then-create sequence.

Fix: take a lock around `place`, or derive the directory name deterministically from the repo and branch (for example uuid5) and use `mkdir(exist_ok=False)`, treating "exists" as a match.

3. [attention · 3] **`.agent/tools/task/task_record_pr.py:21`** — Failure partway through leaves a half-built task

```python
directory.mkdir(parents=True)
atomic_write(directory / ".task-id", ...)
atomic_write(directory / "SPEC.md", ...)
append_pr(directory, found.url)
```

If `SPEC.md` or `append_pr` raises, the directory is left with `.task-id` and no `SPEC.md` or PR record. Later `tasks_in` calls may mis-parse it, and `head(r)` would return empty, so it counts as not CLOSED and could be chosen as an "open" match. A later PR on that branch would then be recorded on this broken task.

Fix: build the task in a temp directory and `rename` it into place, or remove the directory on exception.

4. [attention · 3] **`.agent/tools/task/task_record_pr.py:20`** — `next(...)` with no default can raise `StopIteration`

```python
owner = next(r for repo in found.repos for r in scoped if r.repo.lower() == repo)
```

`scoped` comes from `tasks_in(tasks_dir, found.repos)`. If its repo matching differs from `r.repo.lower() == repo` in any way (case or normalization of `found.repos`, such as `repo` not being lowercased), the generator is empty. The hook then crashes with a bare `StopIteration` after the PR already exists. Inside a hook this is probably swallowed, so the PR silently never appears in `crew ls`. I could not confirm how `tasks_in` normalizes, because it isn't in the package.

Fix: pass a default and return a diagnostic message, or reuse `scoped[0]` when only one repo matches.

5. [nit · 3] **`.agent/tools/task/task_record_pr.py:12`** — Non-ASCII titles all collapse to the slug `pr`

```python
re.sub(r"[^a-z0-9]+", "-", title.lower()) ... or "pr"
```

PR titles in non-Latin scripts, or titles that are all punctuation, all get the slug `pr`. Tasks then become indistinguishable in `crew ls`, and any slug-keyed lookup would collide.