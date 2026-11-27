**Critical**

**Task 4** — "rewrite `.cursor/agents/references/reviewer-contract.md`… turn the 'One issue per finding'… into bullets and tighten the wording" is scope creep. No acceptance criterion and no `## Tests` row covers it. It is also a prompt every persona reads first, so rewording the severity section changes review behavior and has nothing to do with package size. The builder cannot check "tighten the wording", and nothing tests that the rewrite preserved the contract. Drop Task 4 and move it to its own spec, or add a criterion and an inspection path for the exact edit.

**Tasks 1–3 / `## Tests`** — Nothing verifies the three-tool pipeline end to end, and the tasks have no per-task verify lines. The Tests section has only `### Unit`. Task 3 changes `crew-reviewer.md`, a prompt that calls the CLI and writes `<persona>.in.md` files, which crosses a process boundary. Task 5 adds the tests last, so Tasks 1–4 have no check of their own when they run. A builder that stops after Task 2 leaves tests that don't cover the new code. Add a `Verify:` line to each task. Move the test rows into Tasks 1 and 2, or pair each test with its task. Add an `### Integration` test that builds a package and runs `check-packages` on both a good and a bad fixture.

**Important**

**Acceptance criteria 1–3** — The criteria give no checkable command. "A generated file appears as one summary line" never defines "generated", for example by lockfile name, a `@generated` marker or a path list, so the builder has to guess. The "product-flow" exemption is also not tied to a file name or marker. Criterion 3 does not say what "breaks a rule" means, such as `diff.patch` still embedded or `## Tasks` still present. Fix by naming the generated-file detection rule and a command per criterion, for example `rg -c 'diff.patch' <pkg>` and a `check-packages` fixture run.

**Task 3** — "build each package from `package.diff` and `spec-context`" doesn't give the output location, the lens name used for product-flow, or what the agent does when `check-packages` exits 1. Nobody answers prompts, so the builder stalls or guesses. Fix by stating the package directory, how the lens is identified, and the failure action (abort dispatch and report).

**Unverified:** I could not find the paths `.agent/tools/review-hunks.py`, `.agent/tools/review-findings.py`, `.cursor/agents/references/reviewer-contract.md`, `crew-reviewer.md`, `evals/test.sh` or the two test files. The workspace holds only SPEC.md, so none of the paths are confirmed. The spec's measured claim of 156 KB and 18 KB is also unverified.

Verdict: 4 finding(s), 2 unverified (the task file paths, and the 156 KB and 18 KB measurement)