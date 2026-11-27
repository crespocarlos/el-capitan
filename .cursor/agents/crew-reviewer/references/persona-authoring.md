# Adding a reviewer persona

Four changes, two of them in code (steps 2 and 4). Miss one and the persona is dispatched with
no package, or never dispatched at all.

1. **Persona file** — `.cursor/agents/reviewer-<name>.md` with YAML frontmatter (`name`,
   `description`, `tools: Read, Grep, Glob  # {{mcp_servers}}`, `readonly: true`, `maxTurns: 12`) and
   a persona prompt: identity, scope boundaries, focus areas, the lens's label table, and its
   `Assessment:` question (the appended `reviewer-contract.md` owns the output shape). Copy the
   frontmatter from an existing persona rather than inventing tool ids; install fills the placeholder
   with the configured docs and code-search servers, and `agents-inherit-tools` fails any other line.
   Never require a specific tool by name in the prompt body: the harnesses' tool surfaces differ, so
   a named tool may not exist on the other side.
   Reviewers are analysis-only; leaving out `readonly: true` fails `crew-lint` with `missing-readonly`,
   and setting it false requires giving the name a class in `AGENT_CLASSES` in `lint_prompts.py`,
   where the exemption and its reason are reviewable. That table is not limited to the agents that
   edit the tree: `reviewer-probe` is in it because it writes one throwaway artifact, runs it, and
   deletes it, and a read-only worker could not run the probe at all — deletion, not `readonly`, is
   what keeps that write honest.
2. **Selection** — add the name to `PERSONAS` and a path pattern to `SELECT_RULES` in
   `crew-review-findings.py`. `select` is what dispatch reads, so `crew-reviewer` Step 4's prose
   alone dispatches nothing. `select` never returns `explorer`, so that persona stays manually
   dispatched.
3. **Context tier** — assign the persona to a tier in
   `.cursor/agents/crew-reviewer/references/context-tiers.md`.
4. **Package assembly** — add the name to `PRIMARY_KINDS` in `crew-assemble-packages.py` with the
   layer kinds its lens reads first. The tool derives its persona list from `PERSONAS`, so a name
   missing from `PRIMARY_KINDS` stops the run with a message naming it instead of silently writing no
   package.

Example: an SRE team could add `reviewer-observability.md`, selected on monitoring and alerting paths,
checking query quality, false-positive risk, and alert actionability.

## Adding a layer-map field

A different change from a persona: it needs the kind vocabulary in `reviewer-layers.md`, the
Primary-kinds table in `context-tiers.md`, and `check_layers` in `crew-review-findings.py`, then
`coverage` to confirm the map still validates.

## Frontmatter keys per harness

Which harness reads which key, `model:`, and backgrounding: `.agent/tools/AGENTS.md` → Authoring
agent and skill files.
