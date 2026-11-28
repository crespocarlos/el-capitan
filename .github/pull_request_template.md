<!-- Title: a Conventional Commit (`feat: ...`, `fix: ...`); release-please builds the changelog from it. -->

## What and why

## How it was checked

<!-- The commands you ran (CONTRIBUTING.md lists the CI checks) and anything you verified by hand. -->

- [ ] `bash evals/test.sh -n auto`
- [ ] `uv run crew-lint.py --budget` (after `--write-readme` if a routing row, skill, agent or the catalog changed)
- [ ] Tests follow the testing policy (`.cursor/agents/references/testing-policy.md`)
- [ ] A removed or renamed command has no caller or doc left
