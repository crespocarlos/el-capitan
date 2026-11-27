# Spec: record-pr matches tasks by repository slug

## Type: bugfix
## Branch: fix/record-pr-slug
## Status
DRAFTING

## Summary
`record-pr` compares a task's `repo_remote_url` with the PR's repository as raw strings, so an ssh remote
never matches an https URL. Compare normalised `owner/name` slugs instead.

## Acceptance criteria
- [ ] A task with `git@github.com:acme/widgets.git` matches a PR of `https://github.com/acme/widgets`.
- [ ] `.git` suffixes and letter case do not matter.

## Tests
### Unit
- **Command**: `bash evals/test.sh evals/tools/test_lifecycle.py`

## Tasks
- [ ] Task 1: in `.agent/tools/task/task_record_pr.py` `tasks_in`, compare `slug_from_url(r.meta["repo_remote_url"])`
      with each PR repository. Verify: `bash evals/test.sh evals/tools/test_lifecycle.py -k record_pr`
- [ ] Task 2: add rows for ssh, https, `.git` and case to `evals/tools/test_lifecycle.py`.
- [ ] Task 3: add `slug_from_url(url) -> str | None` to `.agent/tools/lib/git.py` (ssh, https, `.git`, case).
