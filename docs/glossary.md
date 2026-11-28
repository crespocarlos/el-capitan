# Glossary

Terms used in the README, these docs, and what the agents say to you. The terms the prompts
themselves must use, one per concept, are defined once in the glossary of
[`src/crew/AGENTS.md`](../src/crew/AGENTS.md); this page explains the same vocabulary to a
person.

| Term | Meaning |
|---|---|
| **Spec** | A `SPEC.md` in a task directory: problem, acceptance criteria, tests, tasks. The artifact the implementer works from. |
| **Gate** | A point where the pipeline stops for your approval. Gate 1 approves the spec; Gate 2 approves the PR. A check a stage runs on its own is verification, not a gate. |
| **Task directory** | `~/.agent/tasks/<uuid>/`, outside any repository. Holds the spec, progress log, review, and report. |
| **Autopilot** | Working through the next pipeline step without re-prompting, between gates only. |
| **Orchestrator** | An agent run inline in your session that owns a stage and dispatches personas: `crew-specwriter`, `crew-reviewer`. |
| **Worker** | An agent dispatched in the background to produce a stage's work: `crew-builder` writes the change, `crew-pr-resolver` analyses review threads read-only. |
| **Persona** | One reviewer or critic lens (adversarial, architecture, code quality, product flow, prompt quality, scope) that reads a package and returns findings. |
| **Hunk** | One contiguous changed block in a diff, numbered `h1`, `h2`, and so on, so a finding and a gate can cite the same change. |
| **Layer map** | The diff grouped into ordered layers (`layers.json`) so each persona reads in a sensible order. Every hunk sits in exactly one layer. |
| **Package** | The context one persona receives: contract, mode, hunk reference, guidance, memory, spec, and the diff. |
| **Finding** | One reported issue, with a severity label, a `file:line` anchor, evidence, and a verdict. |
| **Unit** | One typed Markdown file in `~/.agent/memory`: a durable lesson, a procedure, a project fact, or an observation. |
| **Inbox** | `~/.agent/memory/.inbox/`: drafted memory units waiting for your approval. Nothing in it is recalled until it is imported. |
| **Guard** | A hook that can block a command or a write: the shell guard (credentials, worker-tree, owner-only and other rules) and the file guard for task specs. See [hooks](hooks.md). |
