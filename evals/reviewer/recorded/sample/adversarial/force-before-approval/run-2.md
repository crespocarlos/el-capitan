Assessment: request-changes — a forced close skips the approval gate.

- **[blocking · 4]** a forced close records unapproved work as DONE
  Anchor: /tmp/reviewer-eval-force-before-approval-x1/.agent/tools/task/task_gates.py:28-29
  `reason` says `PR opened` for any URL, whatever the state was, so Gate 1 is invisible in the log.
  Fix: keep `closed:` for every forced close.
