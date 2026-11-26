"""What verify must never mirror: workflows, jobs and steps that can publish, deploy or run with secrets.

A mirrored gate runs on the user's machine with the user's credentials (`~/.npmrc`, a `gh` token), so
anything that can publish is left out and recorded in `skipped`, which makes the run partial (NOT
VERIFIED) instead of silently smaller:

- a workflow with neither a `push` nor a `pull_request` trigger (schedule, dispatch, release) is not
  CI: it is recorded as `<file>: not CI (on: ...)` and does not make the run partial.
- a CI workflow is mirrored unless it also has `pull_request_target`, `workflow_run` or `release`,
  or its only `push` is filtered by `tags` with no `branches` (a release trigger); those are
  recorded as `<file>: workflow not mirrored (on: ...)`, which makes the run partial.
- a job with a job-level `if:` is recorded and not mirrored (the `if:` usually gates a publish).
- as a last line of defence, a step whose command runs a publish or deploy command on any line or
  any `&&`/`;`/`||` segment (`npm publish`, `docker push`, `gh release create`, `git push`, ...) is
  recorded and not mirrored.
"""
from __future__ import annotations

import re

DANGEROUS = {"pull_request_target", "workflow_run", "release"}
PUBLISH = re.compile(
    r"^(?:\w+=\S*\s+)*(?:sudo\s+)?(?:(?:npm|pnpm)\s+publish|yarn\s+(?:npm\s+)?publish|docker\s+push"
    r"|gh\s+release\s+(?:create|upload|edit)|twine\s+upload|cargo\s+publish|gem\s+push|git\s+push)\b")


def trigger_map(doc: dict) -> dict[str, object]:
    """`{event: filter}` of a workflow's `on:`, written as a string, a list or a map (and the YAML 1.1 `True` key)."""
    on = doc.get("on", doc.get(True))
    if isinstance(on, dict):
        return {str(key): value for key, value in on.items()}
    if isinstance(on, list):
        return {str(item): None for item in on}
    return {part.strip(): None for part in str(on or "").strip("[] ").split(",") if part.strip()}


def tags_only(value: object) -> bool:
    """True for a `push` filter that names `tags` and no branch filter: it runs on a release tag."""
    return isinstance(value, dict) and ("tags" in value or "tags-ignore" in value) \
        and not ({"branches", "branches-ignore"} & set(value))


def is_ci(doc: dict) -> bool:
    """True when push (not tags-only) or pull_request is present and no dangerous event is."""
    found = trigger_map(doc)
    if DANGEROUS & set(found):
        return False
    return "pull_request" in found or ("push" in found and not tags_only(found["push"]))


def has_ci_trigger(doc: dict) -> bool:
    """True when the workflow runs on `push` or `pull_request` at all; without either it is not CI."""
    return bool({"push", "pull_request"} & set(trigger_map(doc)))


def not_mirrored(path: str, doc: dict) -> str:
    """The skipped entry of a workflow left out: `not CI` when it has no CI trigger, else `workflow not mirrored`."""
    kind = "workflow not mirrored" if has_ci_trigger(doc) else "not CI"
    return f"{path}: {kind} (on: {', '.join(trigger_map(doc)) or 'none'})"


def job_if(job_id: str, job: dict) -> str:
    """The skipped entry of a job gated by a job-level `if:`, or ''."""
    return f"{job_id}: job with an if:, not mirrored" if job.get("if") else ""


def publishes(command: str) -> bool:
    """True when any line or any `&&`, `;`, `||` segment of the command starts a publish or deploy command."""
    return any(PUBLISH.match(part.strip()) for line in command.splitlines() for part in re.split(r"&&|\|\||;", line))
