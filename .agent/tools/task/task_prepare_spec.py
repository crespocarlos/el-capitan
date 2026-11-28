"""`crew-task.py prepare-spec`: crew-specwriter's setup before the explorer, in one call.

A new task directory under a fresh UUID with `.task-id` (remote, branch, slug, creation time), the template's
path, recalled memory, the spec run directory, and the explorer prompt with its dispatch marker, guidance and
memory filled in and `TODO(prepare)` where the research questions go. Prints TASK_DIR, then one summary line.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from task_guidance import collect, memory_context
from task_guidance_kinds import render
from task_prepare import StepFailed

from lib.clock import utc_now, utc_stamp
from lib.git import GitError, current_branch, remote_url, toplevel
from lib.reply_marker import write_expect

PLACEHOLDER = "TODO(prepare)"
EXPLORER = "specwriter-explorer"


def add_prepare_spec_parser(commands) -> None:
    parser = commands.add_parser("prepare-spec", help="crew spec's setup in one call")
    parser.add_argument("--slug", required=True, help="lowercase, hyphens, about 50 characters")
    parser.add_argument("--bug", action="store_true", help="use the bug template")
    parser.add_argument("--paths", nargs="*", default=[], help="files the request names, for guidance")
    parser.add_argument("--tasks-dir", type=Path, default=None, help="default ~/.agent/tasks")


def guidance_text(record: dict, paths: list[str]) -> str:
    """Each guidance file once, ranked for the explorer and capped (`task_guidance_kinds`), or "none"."""
    return render("explorer", record["files"], paths)[0].rstrip() or "none"


def explorer_prompt(marker: str, task_dir: Path, repo: str, paths: list[str], guidance: str, recalled: str) -> str:
    return "\n".join([
        marker, f"crew-task: {task_dir}", "## Research questions",
        f"{PLACEHOLDER}: 3-6 questions about existing code: where X lives, how Y is done today, which tests cover Z",
        "", "## Repo context", f"Repo: {repo}", f"Likely modules: {PLACEHOLDER}: hints from the request",
        f"Specific files mentioned: {', '.join(paths) or 'none'}", "", "## Project guidance", guidance, "",
        "## Recalled patterns", recalled.strip() or "none", "", "---", "",
        "Explore now. Follow the output format in your persona definition.", ""])


def new_task(tasks_dir: Path, root: Path, slug: str) -> Path:
    """The task directory with its `.task-id`; StepFailed (exit 1) without an origin remote or a branch."""
    url = remote_url(root, "origin")
    try:
        branch = current_branch(root)
    except GitError as error:
        raise StepFailed(".task-id", str(error), 1) from error
    if not url:
        raise StepFailed(".task-id", "no `origin` remote", 1)
    identity = str(uuid.uuid4()).upper()
    task_dir = tasks_dir / identity
    task_dir.mkdir(parents=True)
    record = {"uuid": identity, "repo_remote_url": url, "branch": branch, "slug": slug,
              "created_at": utc_stamp()}
    (task_dir / ".task-id").write_text(json.dumps(record) + "\n", encoding="utf-8")
    return task_dir


def run_steps(args: argparse.Namespace) -> tuple[Path, str]:
    step = "repo"
    try:
        root = toplevel(None)
        step = "template"
        template = Path.home() / ".agent" / ("_BUG_SPEC_TEMPLATE.md" if args.bug else "_SPEC_TEMPLATE.md")
        if not template.is_file():
            raise StepFailed(step, f"{template} is missing; run install.sh")
        step = ".task-id"
        task_dir = new_task(args.tasks_dir or Path.home() / ".agent" / "tasks", root, args.slug)
        step = "memory"
        recalled, _ = memory_context("plan", args.slug, args.paths, root=root)
        step = "explorer"
        spec_run = task_dir / "spec-agents" / utc_now().strftime("%Y%m%dT%H%M%SZ")
        spec_run.mkdir(parents=True)
        guidance = guidance_text(collect(root, [root / p for p in args.paths] or [root]), args.paths)
        text = explorer_prompt(write_expect(spec_run, EXPLORER), task_dir, root.name, args.paths, guidance,
                               recalled or "none")
        target = spec_run / f"{EXPLORER}.prompt.md"
        target.write_text(text, encoding="utf-8")
    except StepFailed:
        raise
    except (GitError, OSError, ValueError) as error:
        raise StepFailed(step, str(error)) from error
    return task_dir, (f"prepare-spec: template {template}; SPEC_RUN {spec_run}; explorer prompt {target}: write its "
                      f"{PLACEHOLDER} lines, then dispatch it")


def main(args: argparse.Namespace) -> int:
    try:
        task_dir, line = run_steps(args)
    except StepFailed as failure:
        print(f"prepare-spec: {failure}", file=sys.stderr)
        return failure.code
    print(task_dir)
    print(line)
    return 0
