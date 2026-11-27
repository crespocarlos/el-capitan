# Contributing

el-capitan is Markdown, shell and Python with no build step. [AGENTS.md](AGENTS.md) is the working
guide for anyone editing it, person or agent; this page is the short version.

## Setup

1. Clone the repository and run `bash install.sh` (`--dry-run` first if you want to see each step).
   Your links then point into this clone, so a change is live in your own sessions at once.
2. Install [`uv`](https://docs.astral.sh/uv/): the test runner, Ruff, codespell, Vale, zizmor and
   actionlint all run through `uvx` at the versions pinned in the repository, so nothing else is
   installed globally.
3. Optional: [`shfmt`](https://github.com/mvdan/sh), so the hook tests exercise both guard parsers
   locally as CI does (`bash evals/install-shfmt.sh <dir>` fetches the pinned binary).

## The checks

CI (`.github/workflows/validate.yml`) runs these: the tests on macOS and Linux (Python 3.9 and
3.12), the lint steps on Linux. Run them before you open a pull request:

```bash
# tests job (macOS and Linux)
bash evals/test.sh -n auto                                   # every test, with pytest-xdist
bash .claude/hooks/fixtures/install.sh                       # install, upgrade and uninstall in a throwaway HOME
python3 evals/memory/run.py                                  # memory evaluation
# lint job (Linux)
python3 .agent/tools/maintenance/crew-lint.py --budget       # repository rules and the prompt budget
bash evals/ruff.sh check .                                   # Python lint
uvx codespell==2.4.1 <paths in validate.yml>                 # spelling
uvx --from vale==3.12.0.0 vale <paths in validate.yml>       # prose rules for prompts and docs
uvx zizmor==1.33.1 --offline .github/workflows               # workflow security
uvx --from actionlint-py==1.7.12.25 actionlint               # workflow syntax
```

`crew-lint.py --list-rules` prints every repository rule. Two of them keep the README honest: the
command tables and the counts are generated, so after changing a routing row, a skill, an agent or
the catalog run `python3 .agent/tools/maintenance/crew-lint.py --write-readme` and commit the result.

## Tests

Follow the [testing policy](.cursor/agents/references/testing-policy.md): test what can regress,
extend an existing test file or case table before adding one, parametrise cases that differ only by
literals, and never pin prose. A guard change adds an allow and a deny case to
`evals/tools/hook_cases.py`.

## Prompts, commands and hooks

- A rule, agent, skill or reference file is a prompt: read the `prompt-authoring` skill
  (`.cursor/skills/prompt-authoring/SKILL.md`) before editing one.
- A new command goes in `.agent/tools/tools.json` and `.agent/tools/TOOLS.md`; a command a `crew`
  verb routes to also needs a routing row in `rules/crew-router.mdc` and a `routes` summary in the
  catalog.
- A renamed or removed command, flag or verb is removed outright, with every caller and doc moved in
  the same change; `crew-lint`'s `removed-command-form` rule fails on the old form.
- A hook is registered in both `.claude/settings.json` and `.cursor/hooks.template.json`.

## Commits and releases

Write [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `refactor:`,
`docs:`, and so on), and give a pull request a title in the same form, since a squash merge uses it.
[release-please](https://github.com/googleapis/release-please) reads them on `main` to write
`CHANGELOG.md`, bump `VERSION` and open the release pull request, so a changelog entry is never
written by hand: `feat` lands under Added, `fix` under Fixed, `refactor` and `perf` under Changed.
`docs`, `test`, `chore` and `ci` stay out of the changelog.

`release-please-config.json` sets `bootstrap-sha` to `cf843d2`, the last commit on `main` before
the release setup and the work it first releases. Without it, and with no tag yet, release-please
would read the whole history, older non-conventional messages included, into the first release.
After the first release its tag is the starting point and the setting no longer matters.

The release pull request is opened with the workflow's `GITHUB_TOKEN`, and GitHub does not start
other workflows for a pull request opened that way, so `validate.yml` does not run on it by itself.
Before merging it, push a commit to its branch yourself (an empty one is enough) so the checks run,
or give the action a GitHub App token. The repository setting "Allow GitHub Actions
to create and approve pull requests" must be on for the action to open the pull request at all.

Report a security issue privately, as [SECURITY.md](SECURITY.md) describes, not in a public issue.
