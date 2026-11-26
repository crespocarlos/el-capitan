#!/usr/bin/env python3
"""Checks for the close-out gate: where a task's review lives and whether it can be found.

The defect this guards is measured, not hypothetical: 25 of 28 `IMPLEMENTING` tasks had a
`REPORT.md`, so the work was finished, and `--mark-done` still refused every one with `review
verdict is ?`. A PR-mode review persists to a temp directory by design, so the gate that read only
`<task>/REVIEW.md` could never see it. Every case here builds a task on disk and asks the real
command, because the bug lived in the resolution of a path rather than in a predicate.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK_TOOLS = ROOT / ".agent" / "tools" / "task"
REVIEW_TOOLS = ROOT / ".agent" / "tools" / "review"
CLI = TASK_TOOLS / "crew-ls.py"

FAILED: list[str] = []

SPEC = "# Probe task\n\n## Status\nIMPLEMENTING\n\n- [x] one criterion\n"


def check(name: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"pass: {name}")
        return
    FAILED.append(name)
    print(f"FAIL: {name}{': ' + str(detail) if detail else ''}")


def run(task: Path, *arguments: str) -> tuple[int, str, str]:
    """Run the close-out gate with `--mark-done <task>`, keeping the argument order argparse wants."""
    result = subprocess.run([sys.executable, str(CLI), "--mark-done", str(task), *arguments],
                            capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def read_module(directory: Path, name: str):
    sys.path.insert(0, str(directory))
    return __import__(name.removesuffix(".py"))


def make_task(base: Path, review_text: str | None = None) -> Path:
    """A task that passes every other gate, with an optional review beside its spec."""
    task = base / "task"
    task.mkdir(parents=True, exist_ok=True)
    (task / "SPEC.md").write_text(SPEC, encoding="utf-8")
    if review_text is not None:
        (task / "REVIEW.md").write_text(review_text, encoding="utf-8")
    return task


def make_temp_review(base: Path, review_text: str) -> Path:
    """A review directory of the shape PR mode writes: outside the task, recorded in run.json."""
    directory = base / "crew-review-probe" / "review" / "20260101000000"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "REVIEW.md").write_text(review_text, encoding="utf-8")
    return directory


def record(task: Path, directory: Path) -> None:
    record_task_review = read_module(REVIEW_TOOLS, "review_workspace.py").record_task_review
    record_task_review(str(task), directory, "pr")


def temp_review_accepts(base: Path) -> None:
    """A passing review in a recorded temp directory closes the task."""
    task = make_task(base / "accept")
    directory = make_temp_review(base / "accept", "Verdict: pass\n")
    record(task, directory)
    recorded = json.loads((task / "run.json").read_text(encoding="utf-8"))
    check("persist records review_dir in run.json",
          recorded.get("review_dir") == str(directory.resolve()), recorded)
    check("persist records the review mode", recorded.get("review_mode") == "pr", recorded)
    code, out, err = run(task, "--pr-url", "https://example.test/pr/1")
    check("a passing temp review closes the task", code == 0, (code, out, err))
    check("the closed status is DONE", "DONE" in (task / "SPEC.md").read_text(encoding="utf-8"))
    check("the gate names the file it read", "review read from" in out and str(directory) in out, out)


def temp_review_refuses(base: Path) -> None:
    """A failing review in the same location still refuses, with the verdict message."""
    task = make_task(base / "refuse")
    directory = make_temp_review(base / "refuse", "Verdict: BLOCK\n")
    record(task, directory)
    code, out, err = run(task, "--pr-url", "https://example.test/pr/1")
    check("a blocking temp review refuses", code == 1, (code, out, err))
    check("the refusal names the verdict", "review verdict is BLOCK, need pass or warn" in err, err)
    check("a refused task stays IMPLEMENTING",
          "IMPLEMENTING" in (task / "SPEC.md").read_text(encoding="utf-8"))
    check("the refusal says where the review was read", "review read from" in err, err)


def missing_review_still_refuses(base: Path) -> None:
    """No review anywhere refuses for the reason the operator can act on."""
    task = make_task(base / "missing")
    code, out, err = run(task, "--pr-url", "https://example.test/pr/1")
    check("no review refuses", code == 1, (code, out, err))
    check("the refusal reports the unknown verdict", "review verdict is ?" in err, err)
    check("the refusal says no review was found", "no review found" in err, err)


def local_review_wins(base: Path) -> None:
    """A review beside the spec is the one the gate reads, even when run.json points elsewhere."""
    task = make_task(base / "local", "Verdict: pass\n")
    directory = make_temp_review(base / "local", "Verdict: BLOCK\n")
    record(task, directory)
    code, out, err = run(task, "--pr-url", "https://example.test/pr/1")
    check("the local review wins over the recorded one", code == 0, (code, out, err))
    check("the local review is the file named", f"review read from {task / 'REVIEW.md'}" in out, out)


def stale_record_refuses(base: Path) -> None:
    """A recorded directory the operator deleted is not a review: the gate reports what it found."""
    task = make_task(base / "stale")
    directory = make_temp_review(base / "stale", "Verdict: pass\n")
    record(task, directory)
    shutil.rmtree(directory)
    code, out, err = run(task, "--pr-url", "https://example.test/pr/1")
    check("a deleted review directory refuses", code == 1, (code, out, err))
    check("a deleted review directory is reported as none", "no review found" in err, err)


def reviewed_at_prefers_the_same_file(base: Path) -> None:
    """The verdict and the `Reviewed at:` commit come from one file, so they cannot disagree."""
    task = make_task(base / "identity")
    directory = make_temp_review(base / "identity", "Verdict: pass\n\nReviewed at: 0123456789abcdef\n")
    record(task, directory)
    review_module = read_module(TASK_TOOLS, "task_review.py")
    gate_module = read_module(TASK_TOOLS, "task_gates.py")
    resolved = review_module.review_file(task)
    check("both reads resolve to the recorded review",
          resolved is not None and resolved.resolve() == (directory / "REVIEW.md").resolve(), resolved)
    check("the reviewed commit comes from that file",
          review_module.reviewed_at(resolved) == "0123456789abcdef", resolved)
    check("the gate names the same file", str(resolved) in gate_module.review_location(task),
          gate_module.review_location(task))


def task_without_spec_is_not_recorded(base: Path) -> None:
    """`record_task_review` leaves a directory that is not a task untouched."""
    directory = base / "not-a-task"
    directory.mkdir()
    read_module(REVIEW_TOOLS, "review_workspace.py").record_task_review(
        str(directory), make_temp_review(base / "ignored", "Verdict: pass\n"), "pr")
    check("a directory with no SPEC.md gets no run.json", not (directory / "run.json").exists(),
          sorted(p.name for p in directory.iterdir()))


def test_a_quoted_reviewed_at_above_the_footer_is_not_the_commit(base: Path) -> None:
    """A finding may quote `Reviewed at:`; only the footer is a claim about the reviewed tree.

    The defect this pins: `reviewed_at` read the whole file, so a review that quoted the line — the
    contract requires quoting, not paraphrasing — satisfied the gate that proves a review covers HEAD
    without ever stating which tree it read.
    """
    task = make_task(base / "quote")
    directory = make_temp_review(base / "quote", (
        "# Review\n\n"
        "1. [attention · 4] **`a.ts:3`** — the footer is stamped too early\n"
        "   The line reads `Reviewed at: deadbee` before the findings are written.\n\n"
        "Verdict: WARN\n> Next: run `crew review address` to resolve blocking findings, or "
        "`crew commit` when the verdict is PASS or WARN.\nReviewed at: 0123456789abcdef\n"
    ))
    record(task, directory)
    review_module = read_module(TASK_TOOLS, "task_review.py")
    resolved = review_module.review_file(task)
    check("a quoted Reviewed at: above the footer is ignored",
          review_module.reviewed_at(resolved) == "0123456789abcdef", resolved)


def test_an_addendum_below_the_footer_keeps_the_commit(base: Path) -> None:
    """A fixed tail window failed open: four appended lines pushed `Reviewed at:` out of it.

    `crew review address` rewrites `REVIEW.md`, so content below the footer is a normal shape; the
    check that proves a review covers HEAD must not go quiet because a note was appended.
    """
    task = make_task(base / "addendum")
    entries = "".join(f"- note {index} added after the fact\n" for index in range(1, 7))
    directory = make_temp_review(base / "addendum", (
        "# Review\n\n"
        "1. [attention · 4] **`a.ts:3`** — nothing\n\n"
        "Verdict: WARN\n> Next: run `crew review address` to continue\n"
        "Reviewed at: 0123456789abcdef\n\n"
        f"## Addendum\n\n{entries}"
    ))
    record(task, directory)
    review_module = read_module(TASK_TOOLS, "task_review.py")
    resolved = review_module.review_file(task)
    check("an addendum below the footer keeps the commit",
          review_module.reviewed_at(resolved) == "0123456789abcdef", resolved)


def progress(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TASK_TOOLS / "crew-progress.py"), *arguments],
                          capture_output=True, text=True)


def listing(tasks: Path, *arguments: str) -> str:
    done = subprocess.run([sys.executable, str(CLI), "--tasks-dir", str(tasks), *arguments],
                          capture_output=True, text=True)
    return done.stdout


def blocked_event_shows_until_the_next_stage(base: Path) -> None:
    """An autopilot stop writes one BLOCKED line that `crew ls` shows until the next stage starts."""
    tasks = base / "blocked-tasks"
    task = make_task(tasks)
    written = progress("blocked", str(task), "stacked base: #51 is not main\nsecond line")
    check("blocked event exits 0", written.returncode == 0, written.stderr)
    lines = (task / "PROGRESS.md").read_text(encoding="utf-8").splitlines() if (task / "PROGRESS.md").is_file() else []
    check("blocked event is one BLOCKED line", len(lines) == 1 and "BLOCKED: stacked base: #51 is not main second line" in lines[0], lines)
    check("crew ls shows the reason", "BLOCKED: stacked base: #51 is not main" in listing(tasks))
    rows = json.loads(listing(tasks, "--json") or "[]")
    check("crew ls --json carries blocked", bool(rows) and rows[0].get("blocked", "").startswith("stacked base"), rows)
    progress(str(task), "IMPLEMENTING → IMPLEMENTING")
    check("the next stage clears it", "BLOCKED" not in listing(tasks))
    cleared = json.loads(listing(tasks, "--json") or "[{}]")
    check("a task never blocked has an empty field", cleared[0].get("blocked") == "", cleared)
    check("blocked on a missing directory fails", progress("blocked", str(base / "none"), "x").returncode == 1)


def blocked_survives_trailing_metric_lines(base: Path) -> None:
    """The same instructions that write BLOCKED then append `METRIC: stage_end`; neither order hides the reason."""
    tasks = base / "metric-tasks"
    task = make_task(tasks)
    progress("blocked", str(task), "waiting on a decision")

    def append(directory: Path, text: str) -> None:
        with (directory / "PROGRESS.md").open("a", encoding="utf-8") as handle:
            handle.write(f"[2026-01-01 00:00:00] {text}\n")

    append(task, "METRIC: stage_end stage=implement workers=1 tokens_reported=unknown")
    append(task, "WORKTREE: current (asked once; recorded in x)")
    check("BLOCKED then stage_end and WORKTREE lines still shows the reason", "BLOCKED: waiting on a decision" in listing(tasks), listing(tasks))
    append(task, "METRIC: stage_start stage=implement")
    check("a later stage_start clears it", "BLOCKED" not in listing(tasks), listing(tasks))
    reverse_tasks = base / "metric-reverse"
    reverse = make_task(reverse_tasks)
    append(reverse, "METRIC: stage_end stage=implement workers=1 tokens_reported=unknown")
    progress("blocked", str(reverse), "late block")
    check("stage_end then BLOCKED shows the reason", "BLOCKED: late block" in listing(reverse_tasks), listing(reverse_tasks))


def spec_writes_ignore_a_fixed_temp_name(base: Path) -> None:
    """Status writes go through a unique temp file: a leftover `SPEC.md.tmp` from another writer is never touched."""
    task = make_task(base / "tmp-close", "Verdict: pass\n")
    (task / "SPEC.md.tmp").mkdir()
    code, out, err = run(task, "--pr-url", "https://example.test/pr/1")
    check("--mark-done writes DONE beside a stray SPEC.md.tmp", code == 0 and "DONE" in (task / "SPEC.md").read_text(encoding="utf-8"),
          (code, out, err))
    tasks = base / "tmp-normalize"
    task = make_task(tasks)
    (task / "SPEC.md").write_text(SPEC.replace("IMPLEMENTING", "implementing"), encoding="utf-8")
    (task / "SPEC.md.tmp").mkdir()
    done = subprocess.run([sys.executable, str(CLI), "--tasks-dir", str(tasks), "--normalize-status", "--apply"], capture_output=True, text=True)
    check("--normalize-status --apply rewrites beside a stray SPEC.md.tmp",
          done.returncode == 0 and "## Status\nIMPLEMENTING\n" in (task / "SPEC.md").read_text(encoding="utf-8"), (done.returncode, done.stderr))
    check("no temp file is left behind", sorted(p.name for p in task.iterdir()) == ["SPEC.md", "SPEC.md.tmp"], sorted(p.name for p in task.iterdir()))


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="crew-lifecycle-"))
    try:
        spec_writes_ignore_a_fixed_temp_name(base)
        blocked_event_shows_until_the_next_stage(base)
        blocked_survives_trailing_metric_lines(base)
        temp_review_accepts(base)
        temp_review_refuses(base)
        missing_review_still_refuses(base)
        local_review_wins(base)
        stale_record_refuses(base)
        reviewed_at_prefers_the_same_file(base)
        task_without_spec_is_not_recorded(base)
        test_a_quoted_reviewed_at_above_the_footer_is_not_the_commit(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("all lifecycle checks passed" if not FAILED else f"lifecycle: {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
