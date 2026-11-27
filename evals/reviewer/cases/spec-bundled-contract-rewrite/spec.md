# Spec: smaller persona packages

## Type: feature
## Branch: feat/package-size
## Status
DRAFTING

## Summary
Each persona package embeds `diff.patch` and the whole SPEC.md. One measured five-persona review sent
156 KB per persona, 18 KB of it the spec's Tasks and Hints, and a generated lockfile's hunks. Embed
`package.diff`, where generated files are collapsed to one line, and give every lens but product-flow
the spec without its Tasks and Hints. Check the written packages before dispatch.

## Acceptance criteria
- [ ] Every `<persona>.in.md` embeds `package.diff`; a generated file appears as one summary line.
- [ ] Every package but product-flow's carries the spec without `## Tasks` and `## Hints`.
- [ ] `review-findings.py check-packages` exits 1 naming the package that breaks either rule.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_review_hunks.py evals/reviewer/test_review_findings.py`

## Tasks
- [ ] Task 1: write `package.diff` in `.agent/tools/review-hunks.py` (generated files collapsed).
- [ ] Task 2: add `spec-context` and `check-packages` to `.agent/tools/review-findings.py`.
- [ ] Task 3: have `crew-reviewer.md` build each package from `package.diff` and `spec-context`, and run
      `check-packages` before dispatch.
- [ ] Task 4: rewrite `.cursor/agents/references/reviewer-contract.md`, which every persona reads first:
      turn the "One issue per finding" and "Say whether the defect pre-exists" headings into bullets and
      tighten the wording of the severity section.
- [ ] Task 5: add rows to `evals/tools/test_review_hunks.py` and `evals/reviewer/test_review_findings.py`.
