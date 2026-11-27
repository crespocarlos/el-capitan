Assessment: request-changes — `--force` now reaches DONE from states that never passed Gate 1.

1. [attention · 4] `.agent/tools/task/task_gates.py:16` — [attention] `--force` with a real PR URL closes a DRAFTING spec as shipped work
```python
if state != "IMPLEMENTING" and not force:
```
From DRAFTING or APPROVED, `--force --pr-url <url>` logs `DRAFTING → DONE (PR opened: <url>)`, so work nobody approved reads as a finished task.
Fix: refuse a PR URL under `--force` unless the task is IMPLEMENTING.
