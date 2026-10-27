---
name: project-sigevents-lifecycle-decisions
description: Settled and open decisions for the SigEvents status lifecycle (#1760): single status writer, flip-flop avoidance, no agent-gated closure, doc/review locations
metadata:
  type: project
---

Settled (2026-10-08): only the status engine moves a live series between active and recovering; agent writes onto a recovering series are skipped; active<->recovering emit no eventStatusChanged (recovering reported as active); probe window >= detector lookback; closure stays deterministic and absence-based (the Verifier, post-closure, is the safety net, not an agent check before closing). Standalone status workflow bootstrapped with cleanup, independent of scheduled discovery.

**Why:** the user's hard requirement is a deterministic status calculation with no scope creep, and flip-flop must be avoided because it retriggers investigations. Alerting v2 gets no asks.

**How to apply:** do not propose agent-gated or verification-before-close designs, or new agent modes, for this work; park them as deferred tradeoffs. Spec of record is the target-architecture doc §4 (diagrams: state machine, target and interim composition, write-authority table). Review with open items (R1 extract recovering guard from the writer, R2 members include off_topic, R3 carried evaluation count) lives in `nightshift-program/workstreams/detection/design-decisions/2026-10-08-lifecycle-review.md`. Related: [[sigevents-hard-rules]].

**Update 2026-10-09 (supersedes the closure parts above):** automatic closure is deferred. A live measurement showed the row-existence probe cannot close real events (7 of 10 matching KI queries return rows in every 15-min bucket; every real event has a chronic member), and "no rows" is ambiguous between recovered and crashed. Ship the lifecycle core (state machine, controller, agent can't pick status); park the probe-driven status workflow (branch `sigevents/status-reconcile`). Closure: operator, cleanup, or the machine acting on discovery's typed assessment when every member is healthy.

**Why:** the user said they were biased on how much the reconciler could do, and wants a simple solution with a clear cut: the model labels evidence once, code does what repeats, the model never votes on status.

**How to apply:** do not propose probe/row-existence closure, `change_point_type` as a recovery signal, or "presence check = safe". Record findings in the lifecycle review file section 8 and doc §4 decision note.

**Update 2026-10-09 (later): the agreed design is verdict-derived status.** Discovery writes per-rule verdicts (healthy ones as `refutes`, on the event); after merging, the members' latest verdicts are assessed and the machine decides (breach -> active, every member healthy -> recovering, never closes). Closure: operator, cleanup, or an optional quiet-period close workflow (cleanup-style, no re-probing). Implemented on branch `sigevents/agent-write-path` (local commit 346c10bc, not pushed); PRs: core = `sigevents/lifecycle-core`, #296617 agent-write-path, #296618 status-reconcile (parked probe, close or repurpose), #296616 attach-investigation head guard (independent). Target arch §4 rewritten; review file section 9.

**Why:** the user wants discovery's assessments (healthy ones included) to be the lifecycle's input, with the machine deciding; the probe cannot close chronic rules.

**How to apply:** the discovery prompt change is unmeasured, so say so and ask for an eval run before suggesting a merge. My earlier claim that the write tool rejects healthy items was wrong on main/core (true only on agent-write-path before this change).

**Update 2026-10-09 (last): keep only what has a driver.** The user wants the PRs to carry only what is used or will be used by them; extras return when a requirement arises, but the engine must stay well structured and easy to extend. Removed: the `evaluation` input, `nextStatus`/`RECOVERING_COUNT`, `status_evaluations`, the director conformance test, controller `annotate`/`severity`. Kept: `assessment`/`operator`/`rule_deleted`, `expectedTimestamp` (cleanup uses it), `status_outcome.ts`. Before removing something, grep for its callers: I removed `expectedTimestamp` once and cleanup still used it.

**How to apply:** do not add speculative parameters, inputs, fields or tests for flows that do not exist; ask what drives it.
