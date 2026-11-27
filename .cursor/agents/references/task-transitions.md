# Task transitions

The detail behind the state machine in `crew-orchestrator.mdc`; read it when a task's status has to
change or be explained.

Transitions are data in `.agent/tools/task/transitions.json`, applied by `crew-task.py reconcile
--apply`. Idle DRAFTING/APPROVED go `ON-HOLD` with the prior state in the status; resume by editing
Status back to the `was` value. Reconcile records the PR it finds for each IMPLEMENTING task's
branch and reports those specs, never rewriting them. A task can hold several PRs; the audit records
are described in `.agent/tools/TOOLS.md`.
