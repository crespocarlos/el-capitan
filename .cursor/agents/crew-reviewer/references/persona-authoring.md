# Adding a reviewer persona

Five changes, three of them in code (steps 2, 4, and 5). Miss one and the persona is dispatched with
no package, or never dispatched at all.

1. **Persona file** — `.cursor/agents/reviewer-<name>.md` with YAML frontmatter (`name`,
   `description`, the search/read `tools` for Claude Code, `readonly: true`, `maxTurns: 12`) and a
   persona prompt: identity, scope boundaries, focus areas, severity definitions, output format. Copy
   the frontmatter from an existing persona rather than inventing tool ids. Never require a specific
   tool by name in the prompt body: the harnesses' tool surfaces differ — one inherits every parent
   tool, the other honours a declared subset — so a named tool may not exist on the other side.
   Reviewers are analysis-only; leaving out `readonly: true` fails `crew-lint` with `missing-readonly`,
   and setting it false requires adding the name to `WRITE_CAPABLE_AGENTS` in `lint_prompts.py`, where
   the exemption and its reason are reviewable.
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
5. **Fixture** — add the persona to an `evals/reviewer/fixtures.json` case, or its prompt is
   unmeasured.

Example: an SRE team could add `reviewer-observability.md`, selected on monitoring and alerting paths,
checking query quality, false-positive risk, and alert actionability.

## Adding a layer-map field

A different change from a persona: it needs the kind vocabulary in `reviewer-layers.md`, the
Primary-kinds table in `context-tiers.md`, and `check_layers` in `crew-review-findings.py`, then
`coverage` to confirm the map still validates.

## Frontmatter keys per harness

Cursor reads `name`, `description`, `model`, `readonly`, and `is_background`, ignores `tools` and
`maxTurns`, and inherits every parent tool — so `readonly: true` is its only tool restriction, and
`crew-lint`'s `missing-readonly` rule fails any agent that lacks it without an exemption. Claude Code
reads `tools` and `maxTurns` and ignores `readonly`; `maxTurns` therefore binds under Claude Code only,
and the explorer budgets are prose-enforced in Cursor. Each frontmatter states which harness reads
which key. Never set `model:`: subagents inherit the invoking model.

**`is_background` is not set in frontmatter here.** Backgrounding is a per-call decision, and the
call sites that need it already pass `run_in_background: true` (`crew-implement` Step 6, and the two
worker rules in `crew-router.mdc`). Setting it in frontmatter would put that fact in two places with
nothing to catch them disagreeing.
