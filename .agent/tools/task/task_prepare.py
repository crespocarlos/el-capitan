"""`crew-task.py prepare-implement`: crew-implement's setup before the builder, in one call.

In order: the spec gate and the batch plan, where the worker runs (`--where`, else the recorded or AGENTS.md choice),
the branch or worktree, `mark-implementing --branch --root`, the stage metrics, `BASELINE.diff`, memory, and the
builder prompts under `<TASK_DIR>/dispatch/` (batches of `BATCH` over `BATCH_OVER` open tasks). No lock: the
orchestrator writes it at dispatch. Prints WORK_DIR and a summary; a failure names its step (1 user decision, else 2).
"""
from __future__ import annotations

import argparse
import contextlib
import re
import sys
from pathlib import Path

from task_gates import load_task, mark_implementing
from task_guidance import memory_context
from task_progress import append_metric
from task_state import head, spec_branch, unresolved
from task_worktree_cli import create, existing_worktree
from task_worktrees import check, choose, record

from lib.git import GitError, base_ref, fetch_remote, output, run_git, toplevel

BATCH, BATCH_OVER = 6, 8
TASK_LINE = re.compile(r"^- \[([ xX])\] ")
LABEL = re.compile(r"^- \[[ xX]\] \**T(\d+)\b")
ATOMIC_WORD = re.compile(r"\batomic\b", re.I)
RANGE = re.compile(r"\bT?(\d+)\s*(?:[-–—]|to)\s*T?(\d+)\b")
NUMBER = re.compile(r"\bT?(\d+)\b")
SPEC_PATH = re.compile(r"`([\w./-]+/[\w.-]+|[\w-]+\.\w+)`")


class StepFailed(Exception):
    """One setup step could not finish; `code` 1 is a state the user decides, 2 a failure."""

    def __init__(self, step: str, message: str, code: int = 2) -> None:
        super().__init__(f"{step}: {message}")
        self.code = code


def add_prepare_parser(commands) -> None:
    parser = commands.add_parser("prepare-implement", help="crew implement's setup in one call")
    parser.add_argument("task_dir", metavar="TASK_DIR", type=Path)
    parser.add_argument("--where", choices=("worktree", "here"),
                        help="where the worker runs; required once per repo when `worktree pref` says ask")
    parser.add_argument("--branch", default="", help="default: the spec's `## Branch:`; run from the drafting checkout")


def tasks(spec: str) -> tuple[list[tuple[int, bool, str]], list[str]]:
    """`(number, done, block)` for each top-level task under `## Tasks`, its indented lines included, numbered by its
    `T<n>` label when every task has one, else by position; and the notes: the section's other lines, and every
    `>` line of the spec, where an atomic group is declared."""
    found: list[list] = []
    notes = [line for line in spec.splitlines() if line.startswith(">")]
    inside = False
    for line in spec.splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Tasks"
            continue
        if not inside:
            continue
        match = TASK_LINE.match(line)
        if match:
            found.append([LABEL.match(line), match.group(1) != " ", line])
        elif found and (line.startswith((" ", "\t")) or not line.strip()):
            found[-1][2] += "\n" + line
        elif line.strip() and line not in notes:
            notes.append(line)
    labelled = bool(found) and all(label for label, _, _ in found)
    return [(int(label.group(1)) if labelled else position, done, block.rstrip())
            for position, (label, done, block) in enumerate(found, 1)], notes


def atomic_groups(notes: list[str], numbers: set[int]) -> list[set[int]]:
    """The task numbers each `atomic` note joins: pairs, ranges (`4-6`, `T4–T6`) and lists (`3, 4 and 5`).

    A note that says atomic in a form that names fewer than two known tasks stops the run (exit 1), since batching
    past it could split a group the author declared."""
    groups = []
    for line in notes:
        if not ATOMIC_WORD.search(line):
            continue
        members = {n for a, b in RANGE.findall(line) for n in range(int(a), int(b) + 1)}
        members |= {int(n) for n in NUMBER.findall(RANGE.sub(" ", line))}
        if len(members) < 2 or not members <= numbers:
            raise StepFailed("batches", f"cannot read the atomic group in {line.strip()!r}; name its tasks, as in "
                             "`> Tasks 4 and 5 are atomic` or `> Tasks 4-6 are atomic`", 1)
        groups.append(members)
    return groups


def batches(open_tasks: list[int], notes: list[str], numbers: set[int]) -> list[list[int]]:
    """One batch, or consecutive batches of at most `BATCH`, never ending inside a declared atomic group."""
    if len(open_tasks) <= BATCH_OVER:
        return [open_tasks]
    groups = atomic_groups(notes, numbers)
    out, current = [], []
    for index, number in enumerate(open_tasks):
        current.append(number)
        later = set(open_tasks[index + 1:])
        if len(current) >= BATCH and not any(number in group and group & later for group in groups):
            out.append(current)
            current = []
    return out + ([current] if current else [])


def spec_paths(spec: str, root: Path) -> list[str]:
    """The file paths the spec names in backticks that exist in the checkout, for memory ranking."""
    return sorted({path for path in SPEC_PATH.findall(spec) if (root / path).exists()})


def place(root: Path, where: str, branch: str, explicit: bool, task_dir: Path) -> tuple[Path, str]:
    """`(WORK_DIR, branch)`: a worktree, or the branch cut (or kept) in this checkout; an explicit `--branch` that is
    not the feature branch already checked out stops the run (exit 1) rather than being dropped."""
    base = base_ref(root)
    if where == "worktree":
        if not branch:
            raise StepFailed("branch", "the spec has no `## Branch:`; pass --branch")
        found = existing_worktree(branch, root)
        if found:
            return Path(found), branch
        code, result = create(branch, base, root)
        if code:
            raise StepFailed("worktree", result or f"crew-worktree exit {code}")
        return Path(result), branch
    state, detail = check(root, task_dir)
    if state == "on-feature-branch":
        if explicit and branch != detail:
            raise StepFailed("branch", f"the checkout is on {detail}, not --branch {branch}; ask the user: switch to "
                             f"{branch} first, use --where worktree, or drop --branch to implement on {detail}", 1)
        return root, detail
    if state == "dirty":
        raise StepFailed("worktree check", f"dirty ({detail}); ask the user: commit, stash, --where worktree, or "
                         "stop", 1)
    if not branch:
        raise StepFailed("branch", "the spec has no `## Branch:`; pass --branch")
    if "/" in base:
        fetch_remote(root, base.split("/", 1)[0], base.split("/", 1)[1])
    exists = run_git(root, ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], check=False).returncode == 0
    output(root, ["switch", branch] if exists else ["switch", "-c", branch, base])
    return root, branch


def prompt(task_dir: Path, work_dir: Path, recalled: str, chosen: list[tuple[int, bool, str]], span: str) -> str:
    header = [f"crew-task: {task_dir}"] + ([f"TASK_RANGE: {span}"] if span else [])
    return "\n".join([*header, "", "Follow ~/.cursor/agents/crew-builder.md (it owns the rules and the report).", "",
                      f"TASK_DIR: {task_dir}", f"WORK_DIR: {work_dir}", f"SPEC: {task_dir / 'SPEC.md'}",
                      f"RECALLED_PATTERNS: {recalled.strip() or 'none'}", "", "## Tasks", "",
                      *(block for _, _, block in chosen), ""])


def plan_batches(spec: str) -> tuple[list[tuple[int, bool, str]], list[list[int]]]:
    """Every task and the batches of the open ones, decided before anything is written: a refusal changes nothing."""
    every, notes = tasks(spec)
    open_numbers = [number for number, done, _ in every if not done]
    return every, batches(open_numbers, notes, {number for number, _, _ in every}) if open_numbers else []


def write_prompts(task_dir: Path, work_dir: Path, recalled: str, every: list, plan: list[list[int]]) -> list[Path]:
    """The builder prompt per batch, under `<TASK_DIR>/dispatch/`; empty when no task is open."""
    folder = task_dir / "dispatch"
    folder.mkdir(exist_ok=True)
    written = []
    for index, numbers in enumerate(plan):
        span = "" if len(plan) == 1 else f"{numbers[0]}-{numbers[-1]}" + (" final" if index == len(plan) - 1 else "")
        name = "builder.md" if not span else f"builder.{numbers[0]}-{numbers[-1]}.md"
        chosen = [item for item in every if item[0] in numbers]
        (folder / name).write_text(prompt(task_dir, work_dir, recalled, chosen, span), encoding="utf-8")
        written.append(folder / name)
    return written


def spec_gate(task_dir: Path) -> tuple[str, str]:
    """`(spec text, title)`; StepFailed unless the spec is APPROVED or IMPLEMENTING."""
    state = load_task(task_dir)
    if state is None:
        raise StepFailed("spec", f"no readable task at {task_dir}")
    if head(state) not in ("APPROVED", "IMPLEMENTING") or (head(state) == "APPROVED" and unresolved(state.text)):
        raise StepFailed("spec", f"status is {head(state) or 'unset'}; expected APPROVED or IMPLEMENTING, with no "
                         "[NEEDS CLARIFICATION] left", 1)
    title = state.text.splitlines()[0].lstrip("#").strip() if state.text else ""
    return state.text, title


def run_steps(args: argparse.Namespace) -> tuple[Path, str]:
    task_dir = args.task_dir.resolve()
    step = "spec"
    try:
        spec, title = spec_gate(task_dir)
        every, plan = plan_batches(spec)
        step = "where"
        root = toplevel(None)
        where = args.where or choose(root)[0]
        if where == "ask":
            raise StepFailed("where", "ask once: \"Use a worktree for this repo? Default: no\", then pass --where", 1)
        if args.where:
            record(root, args.where, task_dir)
        step = "worktree"
        work_dir, branch = place(root, where, args.branch or spec_branch(spec), bool(args.branch), task_dir)
        step = "mark-implementing"
        with contextlib.redirect_stdout(sys.stderr):  # its own lines; stdout stays WORK_DIR and the summary
            refused = mark_implementing(task_dir, branch, work_dir)
        if refused:
            raise StepFailed(step, "refused; its message is above")
        append_metric(task_dir, "implement_start")
        append_metric(task_dir, "stage_start stage=implement")
        step = "baseline"
        baseline = task_dir / "BASELINE.diff"
        if not baseline.is_file():
            baseline.write_text(output(work_dir, ["diff", "HEAD"]), encoding="utf-8")
        step = "memory"
        recalled, _ = memory_context("implement", title, spec_paths(spec, work_dir), root=work_dir)
        step = "dispatch"
        written = write_prompts(task_dir, work_dir, recalled or "none", every, plan)
    except StepFailed:
        raise
    except (GitError, OSError, ValueError) as error:
        raise StepFailed(step, str(error)) from error
    workers = f"{len(written)} worker{'s' if len(written) != 1 else ''}: {', '.join(map(str, written))}" \
        if written else "no open task"
    return work_dir, f"prepare-implement: {branch} ({where}); {workers}; write the lock at dispatch"


def main(args: argparse.Namespace) -> int:
    try:
        work_dir, line = run_steps(args)
    except StepFailed as failure:
        print(f"prepare-implement: {failure}", file=sys.stderr)
        return failure.code
    print(work_dir)
    print(line)
    return 0
