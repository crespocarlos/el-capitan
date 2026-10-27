---
name: prompt-no-repair-steps
description: "Discovery prompt fixes must remove the root cause (one owner per decision, contradiction at the source), not add a late rule that repairs an earlier step"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 010ebad9-a2a2-4e56-b180-b629b7c2867e
  modified: 2026-10-27T09:59:58.745Z
---

When an eval failure points at the discovery prompt, do not append a corrective bullet, pre-write check or extra step. Find the instruction that caused it (usually two places disagreeing, or a decision made in more than one step), fix it there, and delete the duplicates.

**Why:** the user saw "many steps trying to fix previous steps" (2026-10-27). Step 6 "Check before write" had grown to ~10 bullets restating schema rules and earlier-step decisions. Anthropic's prompting guide: explain why, say what to do, prefer general instructions over prescriptive steps, remove over-prompting, structure with XML tags and examples. OpenAI's GPT-5 guide: contradictory or vague instructions cost more than they help, and prompts that many people edit need a contradiction review.

**How to apply:** (1) name the owner of each decision (eligibility, topology, severity) and make later steps consume its output; (2) leave schema-enforced constraints to the tool schema and its error messages; (3) a failure seen in one run is a hypothesis, so measure over repetitions before adding wording; (4) prefer one worked example to several rules. Related: [[feedback-challenge-dont-accept]], [[feedback-prompt-engineering-discovery]].

Root causes found 2026-10-27: Step 6.1 "each rule_uuid appears in exactly one item" and the events_write description "One call assigns every batch detection" contradicted `<eligibility>` (not_checked = not written), so the agent wrote not_checked items. Topology for continuations had no single owner (Step 2 bind, Step 3 finalize, Step 6 copy). Severity "completion unresolved" is stated in 4 places.
