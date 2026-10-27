---
name: challenge-dont-accept
description: "User expects pushback on design/architecture work — challenge reviewer findings and user prompts alike; never collapse an architecture diagram to a concept map when told it is \"complicated\""
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 0211c1ed-04ca-4e67-bae6-6acdec5573f6
  modified: 2026-09-23T14:23:49.872Z
---

Challenge before accepting — reviewer findings, my own prior edits, and the user's one-line prompts alike. Say what I disagree with and why before changing the doc.

**Why:** On the discovery architecture doc (2026-09-23) I accepted all 7 review findings with 0 rejects, then on "a bit complicated, no?" collapsed a correct subsystem-and-blocks diagram into a five-box concept map. User: "target architecture has DOWNGRADED A LOT. you're just accepting anything and making whatever changes. please be more critical." Their original FigJam (three subsystems, ~20 blocks, clear flows) was the right abstraction level all along; the fix was to remove plumbing noise, not blocks.

**How to apply:**
- "Too complicated" means remove implementation plumbing (indexes, executors, internal populations, other teams' internals) — keep every block that is a real component with a single responsibility.
- After a multi-lens review, re-check each accepted fix for what it silently removes (e.g. "no source for criticality" was wrong — KI `severity_score` exists; "agent has zero tools" is a trade-off, not a conclusion). Record trade-offs in the doc's Decisions section instead of picking silently.
- Verify code claims from reviewers before letting them stand; two of the "blocking" ones needed a grep.
- Forked research agents will edit files despite "research only, no edits" (happened 2026-09-23: a KI-schema research fork rewrote a dozen sections of the design doc, including undecided design points). For research, say explicitly "you have no write permission; return findings as text" AND diff the target file afterwards; treat any unsigned design change as a proposal to surface, not a fact.
- Never invent an artifact or borrow a neighbour's term for something different. The "detection-class tree" was my invention using Investigations' "decision tree" vocabulary; user: "you need to ground it, not invent, probably take some inspiration in what investigation/deductive is doing." Read the adjacent team's code/PRs first (nightshift_investigations: symptom-keyed Mermaid trees, Cortex pages-as-KIs, task-keyed memories) and reuse their model or differ with stated reasons.
- When the user pushes back, name the specific failure concretely, fix it, and list what else I over-accepted — don't just redo the last edit.
