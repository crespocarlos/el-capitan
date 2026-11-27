#!/usr/bin/env python3
"""A task's life through `crew-task.py`: the status contract, the gates, reconcile, the close-out, the lock, gc.

`## Status` holds one token per state and the migration settles legacy spellings once. Gate 1
(`mark-approved`) and Gate 2 (`mark-done`) refuse what they must and write one PROGRESS line when they
pass; `reconcile --apply` holds idle specs and reports its write failures in its exit code; the
session-start hook prints what reconcile did. A PR-mode review persists outside the task, so the
close-out gate must find it there and read its verdict and `Reviewed at:` from the same file. The
worker lock and the once-per-repo worktree choice round-trip on a real repository. Every command runs
in this process through `cli_runner`; the hook runs under bash.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from cli_runner import run as cli
from task_fixture import record_status

ROOT = Path(__file__).resolve().parents[2]
TASK_TOOLS = ROOT / ".agent" / "tools" / "task"
REVIEW_TOOLS = ROOT / ".agent" / "tools" / "review"
LS = TASK_TOOLS / "crew-ls.py"
TASK = TASK_TOOLS / "crew-task.py"
sys.path[:0] = [str(TASK_TOOLS), str(REVIEW_TOOLS)]

import review_workspace  # noqa: E402
import task_gates  # noqa: E402
import task_state  # noqa: E402
import task_status  # noqa: E402

SPEC = "# Probe task\n\n## Status\nIMPLEMENTING\n\n- [x] one criterion\n"
STATES = ("DRAFTING", "APPROVED", "IMPLEMENTING", "ON-HOLD", "DONE")
HOLD = "ON-HOLD (auto-hold: no activity 14d; was {})"
OLD = 1790812800  # 2026-10-01, far past the 14-day idle window
PR_ONE, PR_TWO = "https://github.com/acme/widgets/pull/1", "https://github.com/acme/widgets/pull/2"


def check(name: str, condition: bool, detail: object = "") -> None:
    assert condition, f"{name}: {detail}"


def task(*arguments: str, cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    return cli(TASK, *arguments, cwd=cwd, env=env)


def ls(tasks: Path, *arguments: str) -> str:
    return cli(LS, "--tasks-dir", str(tasks), *arguments).stdout


def spec(directory: Path, status: str, boxes: str = "- [x] a", review: str | None = None, old: bool = False, extra: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SPEC.md").write_text(f"# T\n\n## Status\n{status}\n\n{extra}{boxes}\n", encoding="utf-8")
    record_status(directory, status)
    if review is not None:
        (directory / "REVIEW.md").write_text(review + "\n", encoding="utf-8")
    if old:
        for path in directory.iterdir():
            os.utime(path, (OLD, OLD))
    return directory


def status_of(directory: Path) -> str:
    return task_status.read_status(directory / "SPEC.md")


def progress_text(directory: Path) -> str:
    path = directory / "PROGRESS.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def refuses(result: subprocess.CompletedProcess, words: str) -> bool:
    return result.returncode != 0 and words in result.stderr


def test_status_contract(tmp: Path) -> None:
    """Every spelling of one state reads as the one contract token; an unknown token names the allowed set."""
    tokens = {task_status.head(status_of(spec(tmp / f"m{i}", value))) for i, value in enumerate(("done", "Done", "DONE ", "done (PR opened: url)", "DONE."))}
    check("every spelling of done normalizes to one token", tokens == {"DONE"}, tokens)
    check("surrounding whitespace is not a state", task_status.head(status_of(spec(tmp / "sp", "  IMPLEMENTING  "))) == "IMPLEMENTING")
    check("each contract state is unchanged by canonicalization", all(task_status.canonical(s) == s for s in STATES))
    check("a suffixed status keeps its suffix", task_status.canonical(HOLD.format("APPROVED")) == HOLD.format("APPROVED"))
    try:
        task_status.token("SHIPPED")
        check("an unknown token is rejected", False, "no StatusError")
    except task_status.StatusError as error:
        check("an unknown token is rejected, naming every allowed state", all(state in str(error) for state in STATES), str(error))
    unknown = spec(tmp / "cli" / "unknown", "SHIPPED")
    shown = cli(LS, "--status-file", str(unknown / "SPEC.md"))
    check("--status-file prints a malformed value and exits 2 naming the allowed set",
          shown.stdout.strip() == "SHIPPED" and shown.returncode == 2 and "DRAFTING" in shown.stderr, (shown.returncode, shown.stderr))
    check("the migration skips an unknown token", "skip:" in task("normalize-status", "--tasks-dir", str(tmp / "cli")).stderr)
    spec(tmp / "home" / ".agent" / "tasks" / "legacy", "done")  # crew-task.py is already loaded under the real HOME
    scratch = cli(TASK, "normalize-status", env={"HOME": str(tmp / "home")}).stdout
    check("a run under a temp HOME reads that HOME's tasks, never the real ones", "would normalize 1 of 1 spec(s)" in scratch, scratch)
    store = tmp / "store"
    for name, value in (("one", "done"), ("two", "done (PR opened: https://example.test/pr/1)"), ("canon", "DONE"), ("open", "IMPLEMENTING")):
        spec(store / name, value)
    check("a dry run reports every legacy spec and writes nothing",
          task_state.normalize_all(store, False, out=io.StringIO()) == 2 and status_of(store / "one") == "done")
    check("the applied run rewrites them, suffix kept, open status untouched",
          task_state.normalize_all(store, True, out=io.StringIO()) == 2 and status_of(store / "one") == "DONE"
          and status_of(store / "two") == "DONE (PR opened: https://example.test/pr/1)" and status_of(store / "open") == "IMPLEMENTING")
    second = io.StringIO()
    check("a second run changes nothing and says so", task_state.normalize_all(store, True, out=second) == 0 and "already canonical" in second.getvalue())
    spec(tmp / "listing" / "legacy", "done")
    spec(tmp / "listing" / "canonical", "DONE")
    check("the listing counts both spellings as done", "2 done" in ls(tmp / "listing"), ls(tmp / "listing"))


ISSUE = "https://github.com/acme/widgets/issues/{}"


@pytest.mark.parametrize("text, expected", [
    ("## Issue: " + ISSUE.format(4) + "\n", ISSUE.format(4)),
    ("Issue: " + ISSUE.format(5) + " (`bug`, `workstream:detection`).\n", ISSUE.format(5)),
    ("**Issue:** " + ISSUE.format(6) + "\n", ISSUE.format(6)),
    ("See [#3](" + ISSUE.format(3) + ").\n\nIssue: #7\n", ISSUE.format(7)),
    ("Issue: other/repo#8\n", "https://github.com/other/repo/issues/8"),
    ("Tracked by " + ISSUE.format(9) + " and " + ISSUE.format(10) + "\n", ISSUE.format(9)),
    ("Phase 1 of [Issue #11](" + ISSUE.format(11) + ").\n", ISSUE.format(11)),
    ("```\nIssue: " + ISSUE.format(1) + "\n```\nPR: https://github.com/acme/widgets/pull/2\n", ""),
    ("## Issue: [the GitHub issue URL when the spec starts from one]\n", ""),
])
def test_issue_spellings(text: str, expected: str) -> None:
    """The `Issue:` line wins, else the first issue URL outside a fence; `#n` takes the task's repository."""
    check(repr(text), task_state.issue_url(text, "acme/widgets") == expected, task_state.issue_url(text, "acme/widgets"))


def test_reconcile(tmp: Path) -> None:
    """Idle drafts and approvals go on hold; open work, finished work and held work keep their status."""
    tasks = tmp / "tasks"
    cases = {  # name: (status, boxes, review, old, expected after reconcile)
        "abandoned": ("ABANDONED", "- [x] a", "Verdict: pass", False, "ABANDONED"),
        "onhold": (HOLD.format("APPROVED"), "- [x] a", "Verdict: pass", False, HOLD.format("APPROVED")),
        "drafting-old": ("DRAFTING", "- [x] a", "Verdict: pass", True, HOLD.format("DRAFTING")),
        "suffixed-old": ("DRAFTING (updated by Task 9; needs approval)", "- [ ] a", None, True, HOLD.format("DRAFTING")),
        "approved-old": ("APPROVED", "- [ ] a", None, True, HOLD.format("APPROVED")),
        "approved-done-old": ("APPROVED", "- [x] a", "Verdict: pass", True, HOLD.format("APPROVED")),
        "drafting-new": ("DRAFTING", "- [ ] a", None, False, "DRAFTING"),
        "implementing-pass": ("IMPLEMENTING", "- [x] a", "Verdict: PASS. No findings.", False, "IMPLEMENTING"),
        "implementing-warn": ("IMPLEMENTING", "- [x] a", "Verdict: warn", False, "IMPLEMENTING"),
        "implementing-nits": ("IMPLEMENTING", "- [x] a", "Verdict: pass-with-nits", False, "IMPLEMENTING"),
        "implementing-rerun": ("IMPLEMENTING", "- [x] a", "Verdict: pass\n\nround 2\nVerdict: BLOCK", False, "IMPLEMENTING"),
        "implementing-old-open": ("IMPLEMENTING", "- [ ] a", "Verdict: pass", True, "IMPLEMENTING"),
        "implementing-nobox": ("IMPLEMENTING", "no boxes", "Verdict: pass", False, "IMPLEMENTING"),
    }
    for name, (status, boxes, review, old, _) in cases.items():
        spec(tasks / name, status, boxes, review, old)
    (tasks / "empty-status").mkdir()
    (tasks / "empty-status" / "SPEC.md").write_text("# T\n\n## Status\n\n## Summary\n\n- [x] a\n", encoding="utf-8")
    applied = task("reconcile", "--tasks-dir", str(tasks), "--apply")
    wrong = {name: status_of(tasks / name) for name, case in cases.items() if status_of(tasks / name) != case[4]}
    check("reconcile --apply sets every expected status", applied.returncode == 0 and not wrong, (applied.stderr, wrong))
    check("an empty status keeps the next section", "## Summary\n" in (tasks / "empty-status" / "SPEC.md").read_text())
    check("a hold writes its PROGRESS transition", "DRAFTING → ON-HOLD" in progress_text(tasks / "drafting-old"))
    table = ls(tasks).splitlines()
    check("crew ls prints the STATE TASK REPO BRANCH REVIEW AGE table",
          table[:1] and table[0].split() == ["STATE", "TASK", "REPO", "BRANCH", "REVIEW", "AGE"], table[:1])
    check("--md prints the same columns as a table", "| STATE | TASK | REPO | BRANCH | REVIEW | AGE |\n|---|---|---|---|---|---|" in ls(tasks, "--md"))
    report = ls(tasks, "--reconcile")

    def section(heading: str) -> str:
        lines, inside = [], False
        for line in report.splitlines():
            if line.startswith(heading):
                inside = True
            elif inside and line[:1].isalpha():
                break
            elif inside:
                lines.append(line)
        return "\n".join(lines)

    ready = section("ready to open PR")
    check("ready to open PR holds the pass and warn reviews only",
          "implementing-pass" in ready and "implementing-warn" in ready
          and not any(name in ready for name in ("nits", "rerun", "old-open", "nobox")), ready)
    check("stalled IMPLEMENTING holds the idle open task only",
          "implementing-old-open" in section("stalled IMPLEMENTING") and "implementing-pass" not in section("stalled IMPLEMENTING"), report)
    held = spec(tmp / "ro" / "apply-ro", "DRAFTING", "- [ ] a", old=True)
    if os.geteuid() != 0:
        held.chmod(0o555)
        failed = task("reconcile", "--tasks-dir", str(held.parent), "--apply")
        held.chmod(0o755)
        check("--apply reports a write failure in its exit code", failed.returncode != 0 and status_of(held) == "DRAFTING", failed.returncode)


def test_gates(tmp: Path) -> None:
    """Gate 1 and Gate 2, with every refusal reason and the one PROGRESS line each pass writes."""
    tasks = tmp / "gates"
    check("mark-implementing refuses a draft", refuses(task("mark-implementing", str(spec(tasks / "draft", "DRAFTING", "- [ ] a"))), "not APPROVED"))
    check("mark-implementing and mark-done refuse a missing spec",
          refuses(task("mark-implementing", str(tasks / "missing")), "no SPEC.md") and refuses(task("mark-done", str(tasks / "missing"), "--pr-url", PR_ONE), "no SPEC.md"))
    approved = spec(tasks / "approved", "APPROVED", review="Verdict: warn")
    (approved / ".task-id").write_text('{"slug":"approved","branch":"main"}', encoding="utf-8")
    task("mark-implementing", str(approved), "--branch", "feat/a")
    check("APPROVED → IMPLEMENTING is written and logged", status_of(approved) == "IMPLEMENTING" and "APPROVED → IMPLEMENTING" in progress_text(approved))
    check("a second mark-implementing says already implementing", "already implementing" in task("mark-implementing", str(approved), "--branch", "feat/a").stdout)
    branch = spec(tasks / "branch", "IMPLEMENTING", review="Verdict: BLOCK", extra="Issue: #12\n\n")
    (branch / ".task-id").write_text('{"slug":"branch","branch":"feature/x","repo_remote_url":"git@github.com:acme/widgets.git"}', encoding="utf-8")
    first = task("mark-done", str(branch), "--pr-url", PR_ONE, cwd=ROOT)
    check("another branch and a blocking verdict still close: IMPLEMENTING → DONE is written with the PR",
          first.returncode == 0 and status_of(branch) == "DONE" and f"IMPLEMENTING → DONE (PR opened: {PR_ONE})" in progress_text(branch), first)
    second = task("mark-done", str(branch), "--pr-url", PR_TWO)
    task("mark-done", str(branch), "--pr-url", PR_TWO)
    record = next(r for r in json.loads(ls(tasks, "--all", "--json", "--repo", "all"))["items"] if r["slug"] == "branch")
    check("a second PR on a DONE task is appended once to its PR list, and crew ls --json carries the list and the issue",
          "already done" in second.stdout and task_state.load(branch).prs == [PR_ONE, PR_TWO]
          and (record["prs"], record["issue"], record["progress"]) == ([PR_ONE, PR_TWO], "https://github.com/acme/widgets/issues/12", "1/1"), record)
    refusals = (
        ("unchecked", spec(tasks / "open", "IMPLEMENTING", "- [ ] a", "Verdict: pass"), ("--pr-url", PR_ONE)),
        ("not IMPLEMENTING", tasks / "draft", ("--pr-url", PR_ONE)),
        ("--pr-url", tasks / "draft", ()),
        ("not a GitHub PR URL", spec(tasks / "free-text", "IMPLEMENTING"), ("--pr-url", "none (committed to main)")),
        ("cannot verify that review", spec(tasks / "unknown-sha", "IMPLEMENTING", review="Verdict: pass\n\nReviewed at: " + "0123456789abcdef" * 2 + "01234567"),
         ("--pr-url", PR_ONE)),
    )
    for words, directory, extra in refusals:
        before = status_of(directory)
        check(f"mark-done refuses: {words}", refuses(task("mark-done", str(directory), *extra), words) and status_of(directory) == before)
    check("a refusal still records the open PR", task_state.load(tasks / "open").prs == [PR_ONE])
    task("mark-done", str(tasks / "open"), "--pr-url", PR_ONE, "--force")
    check("--force closes an unchecked task", status_of(tasks / "open") == "DONE")
    note = task("mark-done", str(tasks / "free-text"), "--pr-url", "none (committed to main)", "--force")
    check("--force accepts a free-text note and records no PR", note.returncode == 0 and status_of(tasks / "free-text") == "DONE"
          and "IMPLEMENTING → DONE (closed: none (committed to main))" in progress_text(tasks / "free-text") and task_state.load(tasks / "free-text").prs == [])
    task("blocked", str(spec(tasks / "quoted", "IMPLEMENTING")), f"waiting: PR opened: {PR_ONE} needs a rebase")
    check("a BLOCKED reason quoting `PR opened:` adds no PR", task_state.load(tasks / "quoted").prs == [])
    check("no review closes the task", close(spec(tasks / "unreviewed", "IMPLEMENTING")).returncode == 0 and status_of(tasks / "unreviewed") == "DONE")
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    ancestor = spec(tasks / "ancestor", "IMPLEMENTING", review=f"Verdict: pass\n\nReviewed at: {head}")
    task("mark-done", str(ancestor), "--pr-url", PR_ONE, cwd=ROOT)
    check("a review of an ancestor of HEAD passes", status_of(ancestor) == "DONE")
    gate1 = spec(tasks / "gate1", "DRAFTING", "- [ ] a")
    task("mark-approved", str(gate1))
    check("DRAFTING → APPROVED, then already approved", status_of(gate1) == "APPROVED" and "already approved" in task("mark-approved", str(gate1)).stdout)
    check("mark-approved refuses another state", refuses(task("mark-approved", str(branch)), "not DRAFTING"))
    for words, extra in (("NEEDS CLARIFICATION", "## Open questions\n- [NEEDS CLARIFICATION: which API?]\n\n"),
                         ("spec-typed-tests", "## Tests\n### Unit\n- **Command**: none\n\n")):
        directory = spec(tasks / words, "DRAFTING", "- [ ] a", extra=extra)
        check(f"mark-approved refuses: {words}", refuses(task("mark-approved", str(directory)), words) and status_of(directory) == "DRAFTING")
    typed = spec(tasks / "typed", "DRAFTING", "- [ ] a", extra="## Tests\n### Unit\n- **Command**: `pytest`\n\n")
    task("mark-approved", str(typed))
    check("a typed Tests block with a command is approvable", status_of(typed) == "APPROVED")
    blocked = spec(tasks / "blocked", "APPROVED", "- [ ] a", extra="## Open questions\n- [NEEDS CLARIFICATION: which API?]\n\n")
    check("an APPROVED spec with an open clarification cannot be implemented", refuses(task("mark-implementing", str(blocked)), "NEEDS CLARIFICATION"))
    recorded = spec(tasks / "recorded", "APPROVED", "- [ ] a")
    (recorded / ".task-id").write_text('{"slug":"recorded","branch":"main"}', encoding="utf-8")
    task("mark-implementing", str(recorded), "--branch", "feat/worktree")
    check(".task-id records the implementing branch", '"branch": "feat/worktree"' in (recorded / ".task-id").read_text())


def test_a_status_written_outside_crew_task_is_tampered(tmp: Path) -> None:
    """A Status changed by a plain file write no longer equals the one crew-task recorded: `crew ls` (table, JSON,
    reconcile) shows `TAMPERED (spec says X, crew-task recorded Y)`, every gate refuses with those words and writes
    nothing, and `restore-status` writes the recorded status back, or with `--accept <note>` records the spec's."""
    tasks = tmp / "tampered"
    draft = spec(tasks / "draft", "DRAFTING", "- [ ] a")
    (draft / ".task-id").write_text('{"slug":"draft","branch":"main"}', encoding="utf-8")
    task("mark-approved", str(draft))
    spec_path = draft / "SPEC.md"
    spec_path.write_text(spec_path.read_text(encoding="utf-8").replace("APPROVED", "IMPLEMENTING"), encoding="utf-8")
    words = "TAMPERED (spec says IMPLEMENTING, crew-task recorded APPROVED)"
    row = next(r for r in json.loads(ls(tasks, "--json", "--repo", "all"))["items"] if r["slug"] == "draft")
    check("crew ls flags it in the table and the JSON", words in ls(tasks, "--repo", "all") and row["tampered"] == words, row)
    check("reconcile lists it and applies no rule to it", words in task("reconcile", "--tasks-dir", str(tasks)).stdout)
    logged = progress_text(draft)
    for gate, extra in (("mark-implementing", ("--branch", "feat/t")), ("mark-done", ("--pr-url", PR_ONE)), ("mark-approved", ())):
        refused = task(gate, str(draft), *extra)
        check(f"{gate} refuses with the same words and writes nothing", refuses(refused, words) and "restore-status" in refused.stderr
              and status_of(draft) == "IMPLEMENTING" and progress_text(draft) == logged, refused.stderr)
    restored = task("restore-status", str(draft))
    check("restore-status writes the recorded status back and logs it", restored.returncode == 0 and status_of(draft) == "APPROVED"
          and "IMPLEMENTING → APPROVED (restore-status)" in progress_text(draft) and "TAMPERED" not in ls(tasks, "--repo", "all"), restored)
    check("the gates pass again", task("mark-implementing", str(draft), "--branch", "feat/t").returncode == 0 and status_of(draft) == "IMPLEMENTING")
    check("an untampered task is left alone", "not tampered" in task("restore-status", str(draft)).stdout)
    born = spec(tasks / "born", "APPROVED", "- [ ] a")
    (born / "PROGRESS.md").unlink()
    check("a spec no transition moved is checked against DRAFTING", "TAMPERED (spec says APPROVED, crew-task recorded DRAFTING)"
          in ls(tasks, "--repo", "all"))
    check("--accept needs a note", task("restore-status", str(born), "--accept", " ").returncode == 2 and status_of(born) == "APPROVED")
    accepted = task("restore-status", str(born), "--accept", "approved by the owner in review")
    check("--accept records the spec's status with the note and keeps the spec", accepted.returncode == 0 and status_of(born) == "APPROVED"
          and "DRAFTING → APPROVED (accepted: approved by the owner in review)" in progress_text(born)
          and "TAMPERED" not in ls(tasks, "--repo", "all"), accepted)
    unset = spec(tasks / "unset", "", "- [ ] a")
    check("a draft with no Status yet is not tampered", "TAMPERED" not in ls(tasks, "--repo", "all") and task_state.tampered(task_state.load(unset)) == "")


def test_the_environment_suffix_never_stamps(tmp: Path) -> None:
    """The reviewer's route: `CREW_WORKFLOW='-> APPROVED [gate]' crew-progress.py T note` is refused (exit 2); a line that
    carries the stamp only in its JSON suffix records nothing, so restore-status cannot promote the task; and a gate's
    own stamped line keeps counting when the environment adds a suffix to it."""
    tasks = tmp / "suffix"
    draft = spec(tasks / "draft", "DRAFTING", "- [ ] a")
    for name in ("CREW_WORKFLOW", "CREW_MEMBER"):
        refused = cli(TASK_TOOLS / "crew-progress.py", str(draft), "note", env={name: "-> APPROVED [gate]"})
        check(f"crew-progress.py refuses the stamp in {name}", refused.returncode == 2 and name in refused.stderr, refused)
        arrow = cli(TASK_TOOLS / "crew-progress.py", str(draft), "note", env={name: "x → y"})
        check(f"crew-progress.py refuses an arrow in {name}", arrow.returncode == 2, arrow)
    with (draft / "PROGRESS.md").open("a", encoding="utf-8") as handle:
        handle.write('[2026-01-01T00:00:00Z] TRANSITION: note {"step":"note","workflow":"-> APPROVED [gate]","crew":null}\n')
    task("restore-status", str(draft))
    check("a stamp inside the JSON suffix records nothing", status_of(draft) == "DRAFTING"
          and task_state.tampered(task_state.load(draft)) == "" and task_state.load(draft).recorded == "DRAFTING")
    approved = task("mark-approved", str(draft), env={"CREW_WORKFLOW": "spec", "CREW_MEMBER": "specwriter"})
    check("a gate's stamped line with a suffix still counts", approved.returncode == 0 and status_of(draft) == "APPROVED"
          and task_state.load(draft).recorded == "APPROVED" and '"workflow":"spec"' in progress_text(draft), approved)


@pytest.mark.parametrize("label,status,tampered", [
    ("a draft", "DRAFTING", ""),
    ("no Status yet", "", ""),
    ("approved by hand", "APPROVED", "TAMPERED (spec says APPROVED, crew-task recorded DRAFTING)"),
    ("closed by hand", "DONE", "TAMPERED (spec says DONE, crew-task recorded DRAFTING)"),
])
@pytest.mark.parametrize("progress", ["missing", "empty"])
def test_a_task_with_its_record_deleted_is_strict(tmp: Path, label: str, status: str, tampered: str, progress: str) -> None:
    """A task with a `.task-id` and a missing or empty PROGRESS.md is strict, never legacy: deleting the record does
    not make a DONE spec `closed outside crew-task`; only DRAFTING or no Status passes."""
    directory = tmp / "t"
    directory.mkdir()
    (directory / "SPEC.md").write_text(f"# T\n\n## Status\n{status}\n\n- [x] a\n", encoding="utf-8")
    (directory / ".task-id").write_text('{"slug": "t"}', encoding="utf-8")
    if progress == "empty":
        (directory / "PROGRESS.md").write_text("", encoding="utf-8")
    loaded = task_state.load(directory)
    check(f"{label}, PROGRESS.md {progress}", (task_state.tampered(loaded), task_state.closed_outside(loaded)) == (tampered, False),
          (task_state.tampered(loaded), loaded.legacy))


def test_only_the_gates_record_a_status(tmp: Path) -> None:
    """crew-progress.py refuses a status target or the gate stamp (exit 2), so it cannot forge the recorded status that
    restore-status would write into SPEC.md; restore-status never writes a status no gate stamped; and a gate appends
    its stamped transition before the spec, so a failed append writes nothing and a failed spec write is reverted."""
    tasks = tmp / "only-gates"
    draft = spec(tasks / "draft", "DRAFTING", "- [ ] a")
    for text in ("DRAFTING → APPROVED", "x -> IMPLEMENTING", "IMPLEMENTING → REVIEW [gate]"):
        forged = cli(TASK_TOOLS / "crew-progress.py", str(draft), text)
        check(f"crew-progress.py refuses {text!r}", forged.returncode == 2 and "refused" in forged.stderr
              and text not in progress_text(draft), forged)
    check("a pipeline step is still a progress note", cli(TASK_TOOLS / "crew-progress.py", str(draft), "IMPLEMENTING → REVIEW").returncode == 0
          and "TAMPERED" not in ls(tasks, "--repo", "all"))
    legacy = tasks / "legacy"
    legacy.mkdir()
    (legacy / "SPEC.md").write_text("# T\n\n## Status\nDRAFTING\n\n- [ ] a\n", encoding="utf-8")
    (legacy / "PROGRESS.md").write_text("[2026-01-01T00:00:00Z] TRANSITION: DRAFTING → APPROVED\n", encoding="utf-8")
    refused = task("restore-status", str(legacy))
    check("restore-status does not write a status no gate stamped", refused.returncode == 2 and "no gate stamped" in refused.stderr
          and status_of(legacy) == "DRAFTING", refused)
    broken = spec(tasks / "broken", "DRAFTING", "- [ ] a")
    (broken / "PROGRESS.md").unlink()
    (broken / "PROGRESS.md").mkdir()
    failed = task("mark-approved", str(broken))
    check("a failed append writes nothing", failed.returncode == 1 and status_of(broken) == "DRAFTING", failed)
    if os.geteuid() == 0:
        pytest.skip("root writes into a read-only directory, so the spec write cannot be made to fail")
    locked = spec(tasks / "locked", "DRAFTING", "- [ ] a")
    locked.chmod(0o555)
    try:
        failed = task("mark-approved", str(locked))
    finally:
        locked.chmod(0o755)
    check("a failed spec write is reverted by a stamped transition back", failed.returncode == 1 and status_of(locked) == "DRAFTING"
          and "APPROVED → DRAFTING (reverted: SPEC.md not written) [gate]" in progress_text(locked)
          and task_state.tampered(task_state.load(locked)) == "", (failed, progress_text(locked)))


@pytest.mark.parametrize("label,progress,tampered,closed_outside", [
    ("legacy: closed by hand after implementing", "[2026-01-01T00:00:00Z] TRANSITION: X → IMPLEMENTING\n", "", True),
    ("legacy: an untyped line counts as a transition", "[2026-01-01 10:00:00] APPROVED → IMPLEMENTING\n", "", True),
    ("legacy: closed by hand with no transition recorded", None, "", True),
    ("legacy: recorded DONE", "[2026-01-01T00:00:00Z] TRANSITION: X → DONE\n", "", False),
    ("legacy: skipped implementation from APPROVED", "[2026-01-01T00:00:00Z] TRANSITION: X → APPROVED\n",
     "TAMPERED (spec says DONE, crew-task recorded APPROVED)", False),
    ("legacy: skipped implementation from DRAFTING", "[2026-01-01T00:00:00Z] TRANSITION: X → DRAFTING\n",
     "TAMPERED (spec says DONE, crew-task recorded DRAFTING)", False),
    ("stamped: DONE without a stamped DONE", "[2026-01-01T00:00:00Z] TRANSITION: APPROVED → IMPLEMENTING [gate]\n",
     "TAMPERED (spec says DONE, crew-task recorded IMPLEMENTING)", False),
    ("stamped: an unstamped DONE after a stamped line does not count",
     "[2026-01-01T00:00:00Z] TRANSITION: APPROVED → IMPLEMENTING [gate]\n[2026-01-02T00:00:00Z] TRANSITION: IMPLEMENTING → DONE\n",
     "TAMPERED (spec says DONE, crew-task recorded IMPLEMENTING)", False),
    ("stamped: DONE recorded", "[2026-01-01T00:00:00Z] TRANSITION: IMPLEMENTING → DONE (PR opened: x) [gate]\n", "", False),
])
def test_a_done_spec_closed_outside_crew_task(tmp: Path, label: str, progress: str | None, tampered: str, closed_outside: bool) -> None:
    """A legacy task (no gate-stamped line) whose DONE spec is recorded IMPLEMENTING, or nothing, was closed by hand
    before the gates stamped: a quiet `closed outside crew-task` note in `crew ls --all`, never TAMPERED. Recorded
    DRAFTING or APPROVED, it skipped implementation and is TAMPERED. A task with any stamped line is strict: DONE needs
    a stamped DONE."""
    tasks = tmp / "done"
    directory = tasks / "t"
    directory.mkdir(parents=True)
    (directory / "SPEC.md").write_text("# T\n\n## Status\nDONE\n\n- [x] a\n", encoding="utf-8")
    if progress:
        (directory / "PROGRESS.md").write_text(progress, encoding="utf-8")
    row = json.loads(ls(tasks, "--all", "--json", "--repo", "all"))["items"][0]
    table = ls(tasks, "--all", "--repo", "all")
    check(f"{label}: JSON", (row["tampered"], row["closed_outside"]) == (tampered, closed_outside), row)
    check(f"{label}: table", (tampered or ("DONE (closed outside crew-task)" if closed_outside else "DONE ")) in table, table)


# where it runs, its --branch, the status and .task-id branch before, whether a sibling task records feat/x:
# the exit code and the .task-id branch and worktree after
@pytest.mark.parametrize("where,given,status,before,sibling,code,branch,worktree", [
    ("feature", "", "APPROVED", "main", False, 0, "feat/x", "feature"),
    ("main", "", "APPROVED", "main", False, 2, "main", None),
    ("other", "", "APPROVED", "main", False, 2, "main", None),
    ("feature", "feat/x", "APPROVED", "main", False, 0, "feat/x", "feature"),
    ("feature", "feat/z", "APPROVED", "main", False, 0, "feat/z", None),  # the checkout does not hold feat/z
    ("other", "feat/y", "APPROVED", "main", False, 0, "feat/y", None),
    ("feature", "", "IMPLEMENTING", "main", False, 0, "feat/x", "feature"),
    ("feature", "", "APPROVED", "main", True, 2, "main", None),  # another task records feat/x
    ("feature", "", "IMPLEMENTING", "feat/old", False, 0, "feat/old", None),  # already started: a bare re-run changes nothing
    ("fork", "", "APPROVED", "main", False, 0, "feat/f", "fork"),  # origin is the fork, upstream the task's repository
])
def test_mark_implementing_branch(tmp: Path, where: str, given: str, status: str, before: str, sibling: bool, code: int, branch: str,
                                  worktree: str | None) -> None:
    """Without --branch the checkout's own branch is taken, never the default branch, another repo's or another task's,
    and an IMPLEMENTING task's started branch stays; the checkout is recorded as `worktree` only when its `origin` or
    `upstream` remote (ssh or https) is the task's and it holds the recorded branch."""
    env = {**os.environ, **GIT_ID}
    trees = {"main": tmp / "main", "feature": tmp / "feature", "other": tmp / "other", "fork": tmp / "fork"}
    for name, remote in (("main", "git@github.com:acme/widgets.git"), ("other", "https://github.com/acme/other.git"),
                         ("fork", "git@github.com:me/widgets.git")):
        subprocess.run(["git", "init", "-q", "-b", "main", str(trees[name])], check=True, env=env)
        subprocess.run(["git", "-C", str(trees[name]), "remote", "add", "origin", remote], check=True, env=env)
        subprocess.run(["git", "-C", str(trees[name]), "commit", "-q", "--allow-empty", "-m", "base"], check=True, env=env)
    subprocess.run(["git", "-C", str(trees["main"]), "worktree", "add", "-q", "-b", "feat/x", str(trees["feature"])], check=True, env=env,
                   capture_output=True)
    subprocess.run(["git", "-C", str(trees["other"]), "switch", "-q", "-c", "feat/x"], check=True, env=env)
    subprocess.run(["git", "-C", str(trees["fork"]), "remote", "add", "upstream", "https://github.com/acme/widgets.git"], check=True, env=env)
    subprocess.run(["git", "-C", str(trees["fork"]), "switch", "-q", "-c", "feat/f"], check=True, env=env)
    if sibling:
        other = spec(tmp / "tasks" / "s", "IMPLEMENTING", "- [ ] a")
        (other / ".task-id").write_text(json.dumps({"slug": "s", "branch": "feat/x", "repo_remote_url": "git@github.com:acme/widgets.git"}),
                                        encoding="utf-8")
    directory = spec(tmp / "tasks" / "t", status, "- [ ] a")
    (directory / ".task-id").write_text(json.dumps({"slug": "t", "branch": before, "repo_remote_url": "https://github.com/Acme/widgets"}),
                                        encoding="utf-8")
    result = task("mark-implementing", str(directory), *(("--branch", given) if given else ()), cwd=trees[where])
    meta = json.loads((directory / ".task-id").read_text(encoding="utf-8"))
    expected_tree = str(trees[worktree].resolve()) if worktree else None
    check("exit code, branch and worktree", (result.returncode, meta["branch"], meta.get("worktree")) == (code, branch, expected_tree),
          (result.stdout, result.stderr, meta))
    if code:
        check("a refusal names --branch and writes nothing", "--branch" in result.stderr and status_of(directory) == status, result.stderr)
    else:
        check("the drafting branch is kept and the status is IMPLEMENTING",
              meta.get("spec_branch", before) == before and status_of(directory) == "IMPLEMENTING", meta)


def test_reconcile_hook(tmp: Path) -> None:
    """The session-start hook prints what reconcile changed and what is waiting, or why it could not run."""
    home = tmp / "hook-home"
    (home / ".agent" / "bin").mkdir(parents=True)
    for name in ("crew-ls.py", "crew-task.py"):
        (home / ".agent" / "bin" / name).symlink_to(TASK_TOOLS / name)
    tasks = home / ".agent" / "tasks"
    spec(tasks / "idle", "DRAFTING", "- [ ] a", old=True)
    spec(tasks / "shipped", "done")
    spec(tasks / "ready", "IMPLEMENTING", review="Verdict: pass")
    spec(tasks / "stuck", "IMPLEMENTING", "- [ ] a", old=True)
    repo, env = tmp / "checkout", {**os.environ, **GIT_ID}
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)

    def commit(branch: str, start: str = "main") -> str:
        if branch != "main":
            subprocess.run(["git", "-C", str(repo), "switch", "-q", "-c", branch, start], check=True, env=env)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", branch], check=True, env=env)
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

    commit("main")
    tip, elsewhere = commit("feat/x"), commit("other", "main")
    subprocess.run(["git", "-C", str(repo), "switch", "-q", "main"], check=True, env=env)
    for name, number, review in (("opened", 1, None), ("covered", 2, f"Verdict: pass\n\nReviewed at: {tip}"),
                                 ("behind", 3, f"Verdict: pass\n\nReviewed at: {elsewhere}")):
        directory = spec(tasks / name, "IMPLEMENTING", review=review)
        (directory / "PROGRESS.md").write_text(f"[2026-01-01T00:00:00Z] PR: {PR_ONE[:-1]}{number}\n", encoding="utf-8")
        record_status(directory, "IMPLEMENTING")
        (directory / ".task-id").write_text(json.dumps({"slug": name, "branch": "feat/x"}), encoding="utf-8")
    hook = ROOT / ".claude" / "hooks" / "spec-status-reconcile.sh"
    out = subprocess.run(["bash", str(hook)], capture_output=True, text=True, env={**os.environ, "HOME": str(home)}, cwd=repo).stdout
    check("the hook reports the hold, the ready to mark done with each PR and one command (the review checked against the task's "
          "branch, not the cwd's main), a PR open but not closable with its reason, the ready and the stalled task",
          all(line in out for line in ("spec-status: idle -> ON-HOLD", "spec-status: 2 ready to mark done: covered (#2), opened (#1)",
                                       f"spec-status: close one with: ~/.agent/bin/crew-task.py mark-done {tasks / 'covered'} --pr-url {PR_ONE[:-1]}2",
                                       "spec-status: 1 PR open, not closable: behind (#3: the review does not cover the branch tip",
                                       "spec-status: 1 ready to open PR: ready", "spec-status: 1 stalled IMPLEMENTING: stuck"))
          and "review pass" not in out and status_of(tasks / "opened") == "IMPLEMENTING", out)
    missing = subprocess.run(["bash", str(hook)], capture_output=True, text=True, env={**os.environ, "HOME": str(tmp / "no-tool")}).stdout
    check("a missing tool is reported with the fix", "crew-task.py missing; re-run install.sh" in missing, missing)


PR_UP = "https://github.com/acme/widgets/pull/7"  # the fork me/widgets's PR, opened on its parent
GH_STUB = """#!/bin/sh
echo "$*" >> "$GH_CALLS"
[ "$GH_OFFLINE" = 1 ] && exit 1
case "$*" in
  "repo view acme/widgets --json defaultBranchRef,parent") echo '{"defaultBranchRef":{"name":"main"},"parent":null}' ;;
  "repo view me/widgets --json defaultBranchRef,parent")
    echo '{"defaultBranchRef":{"name":"main"},"parent":{"name":"widgets","owner":{"login":"acme"}}}' ;;
  "pr list --head feat/x --repo acme/widgets --state all --json url") echo '[{"url":"<PR>"}]' ;;
  "pr list --head "*" --repo me/widgets --state all --json url") echo '[]' ;;
  "pr list --head "*" --repo acme/widgets --state all --json url,headRepositoryOwner")
    echo '[{"url":"https://github.com/acme/widgets/pull/98","headRepositoryOwner":{"login":"other"}},{"url":"<UP>","headRepositoryOwner":{"login":"me"}}]' ;;
  *) echo '[{"url":"https://github.com/acme/widgets/pull/99"}]' ;;
esac
""".replace("<PR>", PR_TWO).replace("<UP>", PR_UP)


@pytest.mark.parametrize("offline", [False, True])
def test_reconcile_finds_prs(tmp: Path, offline: bool) -> None:
    """Reconcile reads each IMPLEMENTING task's branch PR (read-only, skipped offline), records it, never closes the task."""
    tasks, stub = tmp / "tasks", tmp / "bin" / "gh"
    for name, branch, boxes in (("found", "feat/x", "- [x] a"), ("trunk", "main", "- [x] a"), ("draft", "feat/x", "- [ ] a")):
        spec(tasks / name, "IMPLEMENTING" if name != "draft" else "DRAFTING", boxes)
        (tasks / name / ".task-id").write_text(json.dumps({"slug": name, "branch": branch, "repo_remote_url": "git@github.com:acme/widgets.git"}))
    stub.parent.mkdir()
    stub.write_text(GH_STUB, encoding="utf-8")
    stub.chmod(0o755)
    env = {"PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}", "GH_CALLS": str(tmp / "calls"), "GH_OFFLINE": "1" if offline else "0"}
    done = task("reconcile", "--tasks-dir", str(tasks), "--apply", env=env)
    calls = (tmp / "calls").read_text().splitlines() if (tmp / "calls").exists() else []
    ready = done.stdout.split("ready to mark done", 1)[-1].split("\n\n")[0].split("ready to open PR")[0]
    expected = [] if offline else [PR_TWO]
    check("the branch PR is recorded and reported ready to mark done; the default branch and a draft are never asked; the status stays",
          done.returncode == 0 and task_state.load(tasks / "found").prs == expected and ("found" in ready) is not offline
          and all("--head main" not in call for call in calls) and len([c for c in calls if c.startswith("pr list")]) == (0 if offline else 1)
          and status_of(tasks / "found") == "IMPLEMENTING" and task_state.load(tasks / "trunk").prs == []
          and ("2 task(s) not checked for a PR yet" in done.stdout) is offline, (done.stdout, done.stderr, calls))
    again = task("reconcile", "--tasks-dir", str(tasks), "--apply", "--pr-budget", "3", env=env)
    more = (tmp / "calls").read_text().splitlines()[len(calls):] if (tmp / "calls").exists() else []
    check("a second run asks gh nothing once every task was answered (cached 24 h), and again when offline left them unchecked",
          again.returncode == 0 and bool(more) is offline, (again.stdout, more))


@pytest.mark.parametrize("repo,found,lists", [
    ("acme/widgets", PR_TWO, ["acme/widgets"]),  # not a fork: one pr list, no parent asked
    ("me/widgets", PR_UP, ["me/widgets", "acme/widgets"]),  # a fork: the parent, only the PR whose head is me's
])
def test_reconcile_asks_a_fork_parent(tmp: Path, repo: str, found: str, lists: list[str]) -> None:
    """A fork's task with no PR in the fork finds its PR on the parent; the parent comes from the cached `repo view`."""
    tasks, stub, calls = tmp / "tasks", tmp / "bin" / "gh", tmp / "calls"
    stub.parent.mkdir()
    stub.write_text(GH_STUB, encoding="utf-8")
    stub.chmod(0o755)
    env = {"PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}", "GH_CALLS": str(calls), "GH_OFFLINE": "0"}

    def run(name: str, branch: str) -> list[str]:
        spec(tasks / name, "IMPLEMENTING")
        (tasks / name / ".task-id").write_text(json.dumps({"slug": name, "branch": branch, "repo_remote_url": f"git@github.com:{repo}.git"}))
        before = calls.read_text().splitlines() if calls.exists() else []
        check(f"reconcile for {name}", task("reconcile", "--tasks-dir", str(tasks), "--apply", env=env).returncode == 0)
        return calls.read_text().splitlines()[len(before):]

    first = run("one", "feat/x")
    check("the task records its PR; pr list asks the task repo, then the parent of a fork only",
          task_state.load(tasks / "one").prs == [found] and [c.split("--repo ")[1].split()[0] for c in first if c.startswith("pr list")] == lists
          and sum(c.startswith("repo view") for c in first) == 1, first)
    second = run("two", "feat/y")
    check("a later task of the same repository reads the default branch and the parent from the cache",
          not any(c.startswith("repo view") for c in second) and [c.split("--repo ")[1].split()[0] for c in second] == lists, second)


def test_pr_lookup_budget(tmp: Path) -> None:
    """Lookups share one budget on an injected clock: a read that outlasts it leaves its task unchecked and uncached;
    a crashing lookup says why; a cached repository is not asked again."""
    import threading

    import task_prs

    tasks, release, clock = tmp / "tasks", threading.Event(), [0.0]
    for name in ("slow", "broken"):
        spec(tasks / name, "IMPLEMENTING")
        (tasks / name / ".task-id").write_text(json.dumps({"slug": name, "branch": f"feat/{name}", "repo_remote_url": "git@github.com:acme/widgets.git"}))
    calls: list[list[str]] = []

    def read(arguments: list[str], timeout: float) -> tuple[int, str]:
        calls.append(arguments)
        if arguments[0] == "repo":
            return 0, '{"defaultBranchRef": {"name": "main"}}'
        if "feat/broken" in arguments:
            raise RuntimeError("boom")
        if not release.is_set():
            clock[0] = 10.0  # the budget runs out while this read is in flight
            release.wait()  # held until the search has returned without it
        return 0, json.dumps([{"url": PR_ONE}])

    slow, broken, cache = task_state.load(tasks / "slow"), task_state.load(tasks / "broken"), tmp / task_prs.CACHE_NAME
    first = task_prs.branch_prs([slow], cache, budget=3, write=True, read=read, clock=lambda: clock[0])
    release.set()
    stored = json.loads(cache.read_text())
    check("past the budget the in-flight task is counted unchecked and not cached; the repository answer is",
          first.found == {} and first.unchecked == 1 and stored["tasks"] == {} and stored["repos"]["acme/widgets"][1] == "main", (first, stored))
    calls.clear()
    errors = io.StringIO()
    with contextlib.redirect_stderr(errors):
        second = task_prs.branch_prs([slow, broken], cache, write=True, read=read)
    check("with no budget every lookup ends; the cached repository is not asked; a crash is a warning and stays unchecked",
          second.found == {tasks / "slow": [PR_ONE]} and second.unchecked == 1 and all(call[0] == "pr" for call in calls)
          and "warning: PR lookup for broken: RuntimeError: boom" in errors.getvalue()
          and set(json.loads(cache.read_text())["tasks"]) == {"slow"}, (second, calls, errors.getvalue()))


def test_bad_transitions(tmp: Path) -> None:
    """A malformed or unknown `transitions.json` is an error that names the file, never a silent policy."""
    tools = tmp / "bad" / "task"
    shutil.copytree(TASK_TOOLS, tools, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / ".agent" / "tools" / "lib", tmp / "bad" / "lib", ignore=shutil.ignore_patterns("__pycache__"))
    tasks = spec(tmp / "bad-tasks" / "a", "DRAFTING", "- [ ] a").parent
    for text, words in (("{bad", "error: transitions.json"),
                        ('{"idle_days":14,"auto":[{"from":["DRAFTING"],"kind":"hold","when":["bogus"],"status":"x","log":"y"}]}', "unknown predicate"),
                        ('{"idle_days":14,"auto":[{"from":["DRAFTING"],"kind":"hold","when":["idle"],"status":"{typo}","log":"y"}]}', "error: transitions.json")):
        (tools / "transitions.json").write_text(text, encoding="utf-8")
        done = subprocess.run([sys.executable, str(tools / "crew-task.py"), "reconcile", "--tasks-dir", str(tasks), "--apply"], capture_output=True, text=True)
        check(f"transitions.json {text[:20]!r}: {words}", done.returncode != 0 and words in done.stderr, done.stderr[-300:])


def make_task(root: Path, review_text: str | None = None) -> Path:
    """A task that passes every other gate, with an optional review beside its spec."""
    directory = spec(root / "task", "IMPLEMENTING", "- [x] one criterion")
    if review_text is not None:
        (directory / "REVIEW.md").write_text(review_text, encoding="utf-8")
    return directory


def temp_review(root: Path, text: str, record_for: Path | None = None) -> Path:
    """A review directory of the shape PR mode writes: outside the task, recorded in run.json."""
    directory = root / "crew-review-probe" / "review" / "20260101000000"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "REVIEW.md").write_text(text, encoding="utf-8")
    if record_for is not None:
        review_workspace.record_task_review(str(record_for), directory, "pr")
    return directory


def close(directory: Path) -> subprocess.CompletedProcess:
    return task("mark-done", str(directory), "--pr-url", PR_ONE)


def test_review_location(tmp: Path) -> None:
    """The close-out gate reads the review beside the spec first, else the recorded PR-mode directory."""
    accept = make_task(tmp / "accept")
    directory = temp_review(tmp / "accept", "Verdict: pass\n", accept)
    recorded = json.loads((accept / "run.json").read_text(encoding="utf-8"))
    check("persist records review_dir and mode in run.json", recorded.get("review_dir") == str(directory.resolve()) and recorded.get("review_mode") == "pr", recorded)
    done = close(accept)
    check("a passing temp review closes the task and names the file", done.returncode == 0 and status_of(accept).startswith("DONE")
          and f"review read from {directory.resolve()}" in done.stdout, (done.stdout, done.stderr))
    refuse = make_task(tmp / "refuse")
    temp_review(tmp / "refuse", f"Verdict: pass\n\nReviewed at: {'0123456789abcdef' * 2}01234567\n", refuse)
    done = close(refuse)
    check("an unverifiable recorded review refuses and says where it was read", done.returncode == 1
          and "cannot verify that review" in done.stderr and "review read from" in done.stderr and status_of(refuse) == "IMPLEMENTING")
    local = make_task(tmp / "local", "Verdict: pass\n")
    temp_review(tmp / "local", "Verdict: BLOCK\n", local)
    done = close(local)
    check("the review beside the spec wins over the recorded one", done.returncode == 0 and f"review read from {local / 'REVIEW.md'}" in done.stdout)
    stale = make_task(tmp / "stale")
    shutil.rmtree(temp_review(tmp / "stale", "Verdict: pass\n", stale))
    done = close(stale)
    check("a deleted review directory is no review: the task closes and says so", done.returncode == 0 and "no review found" in done.stdout)
    not_task = tmp / "not-a-task"
    not_task.mkdir()
    review_workspace.record_task_review(str(not_task), temp_review(tmp / "ignored", "Verdict: pass\n"), "pr")
    check("a directory with no SPEC.md gets no run.json", not (not_task / "run.json").exists())
    tmp_close = make_task(tmp / "tmp-close", "Verdict: pass\n")
    (tmp_close / "SPEC.md.tmp").mkdir()
    check("mark-done writes DONE beside a stray SPEC.md.tmp", close(tmp_close).returncode == 0 and status_of(tmp_close).startswith("DONE"))


def test_reviewed_at(tmp: Path) -> None:
    """The verdict and `Reviewed at:` come from one file, and only its footer line counts."""
    footer = "Verdict: WARN\n> Next: run `crew review address` to continue\nReviewed at: 0123456789abcdef\n"
    for name, text in (("identity", "Verdict: pass\n\nReviewed at: 0123456789abcdef\n"),
                       ("quote", "# Review\n\n1. [attention · 4] **`a.ts:3`** — The line reads `Reviewed at: deadbee` early.\n\n" + footer),
                       ("addendum", "# Review\n\n" + footer + "\n## Addendum\n\n" + "".join(f"- note {i}\n" for i in range(6)))):
        directory = make_task(tmp / name)
        recorded = temp_review(tmp / name, text, directory)
        resolved = task_status.review_file(directory)
        check(f"{name}: the recorded review is read and its footer commit is the one",
              resolved is not None and resolved.resolve() == (recorded / "REVIEW.md").resolve()
              and task_status.reviewed_at(resolved) == "0123456789abcdef" and str(resolved) in task_gates.review_location(directory), resolved)


def test_force_closes_any_open_state(tmp: Path) -> None:
    """`mark-done --force` closes a stale DRAFTING, APPROVED or ON-HOLD task with `closed: <note>` (stripped, any case
    of the prefix) and ends its BLOCKED line. Refused, nothing written: a draft without `--force`, a PR URL before
    approval, ABANDONED, an unset status, an empty note."""
    tasks = tmp / "stale"
    draft = spec(tasks / "draft", "DRAFTING", "- [ ] a")
    check("DRAFTING without --force is refused", refuses(task("mark-done", str(draft), "--pr-url", "closed: stale"), "not a GitHub PR URL")
          and refuses(task("mark-done", str(draft), "--pr-url", PR_ONE), "not IMPLEMENTING") and status_of(draft) == "DRAFTING")
    for words, directory, note in (("approve the spec first", draft, PR_ONE), ("is ABANDONED", spec(tasks / "abandoned", "ABANDONED"), "closed: stale"),
                                   ("is unset", spec(tasks / "unset", ""), "closed: stale"), ("--pr-url is empty", draft, "  closed:  ")):
        before, logged = status_of(directory), progress_text(directory)
        check(f"--force refuses: {words}", refuses(task("mark-done", str(directory), "--pr-url", note, "--force"), words)
              and status_of(directory) == before and progress_text(directory) == logged, progress_text(directory))
    held = spec(tasks / "held", HOLD.format("DRAFTING"), "- [ ] a")
    task("blocked", str(held), "deprioritized")
    check("an ON-HOLD task shows its BLOCKED line", "BLOCKED: deprioritized" in ls(tasks, "--all", "--repo", "all"))
    for state, directory, note in (("DRAFTING", draft, "closed: stale"), ("APPROVED", spec(tasks / "approved", "APPROVED", "- [ ] a"), "  Closed: stale "),
                                   ("ON-HOLD", held, "stale")):
        closed = task("mark-done", str(directory), "--pr-url", note, "--force")
        check(f"--force closes {state}", closed.returncode == 0 and status_of(directory) == "DONE"
              and f"{state} → DONE (closed: stale)" in progress_text(directory), (closed, progress_text(directory)))
    row = next(r for r in json.loads(ls(tasks, "--all", "--json", "--repo", "all"))["items"] if r["slug"] == "held")
    check("closing ends the open BLOCKED line", row.get("blocked") == "", row)


def test_blocked_events(tmp: Path) -> None:
    """An autopilot stop writes one BLOCKED line that `crew ls` shows until the next stage starts."""
    tasks = tmp / "blocked-tasks"
    directory = make_task(tasks)
    written = task("blocked", str(directory), "stacked base: #51 is not main\nsecond line")
    lines = [line for line in progress_text(directory).splitlines() if "BLOCKED" in line]
    check("blocked writes one BLOCKED line", written.returncode == 0 and len(lines) == 1
          and "BLOCKED: stacked base: #51 is not main second line" in lines[0], lines)
    rows = json.loads(ls(tasks, "--json"))["items"]
    check("crew ls and --json show the reason", "BLOCKED: stacked base: #51 is not main" in ls(tasks)
          and rows and rows[0].get("blocked", "").startswith("stacked base"), rows)
    cli(TASK_TOOLS / "crew-progress.py", str(directory), "IMPLEMENTING → REVIEW")
    check("the next stage clears it", "BLOCKED" not in ls(tasks) and json.loads(ls(tasks, "--json"))["items"][0].get("blocked") == "")
    check("blocked on a missing directory fails", task("blocked", str(tmp / "none"), "x").returncode == 1)

    def append(text: str) -> None:
        with (directory / "PROGRESS.md").open("a", encoding="utf-8") as handle:
            handle.write(f"[2026-01-01 00:00:00] {text}\n")

    task("blocked", str(directory), "waiting on a decision")
    append("METRIC: stage_end stage=implement workers=1 tokens_reported=unknown")
    append("WORKTREE: current (asked once; recorded in x)")
    check("BLOCKED then stage_end and WORKTREE lines still shows the reason", "BLOCKED: waiting on a decision" in ls(tasks))
    append("METRIC: stage_start stage=implement")
    check("a later stage_start clears it", "BLOCKED" not in ls(tasks))
    append("METRIC: stage_end stage=implement workers=1 tokens_reported=unknown")
    task("blocked", str(directory), "late block")
    check("stage_end then BLOCKED shows the reason", "BLOCKED: late block" in ls(tasks))


def test_lock_and_worktree(tmp: Path) -> None:
    """`lock write|remove` round-trips outside git status; `worktree pref|record|check` answer once per repo."""
    tree = tmp / "tree"
    subprocess.run(["git", "init", "-q", str(tree)], check=True)
    lock = tree / ".crew-worker.lock"
    task("lock", "write", str(tree), "--task", "T-123")
    task("lock", "write", str(tree), "--task", "T-123")
    body = lock.read_text(encoding="utf-8").splitlines() if lock.is_file() else []
    status = subprocess.run(["git", "-C", str(tree), "status", "--porcelain"], text=True, capture_output=True).stdout
    check("the lock holds task= and started=, is excluded once from git status",
          "task=T-123" in body and any(line.startswith("started=") and line[8:].isdigit() for line in body)
          and ".crew-worker.lock" not in status and (tree / ".git" / "info" / "exclude").read_text().count(".crew-worker.lock") == 1, body)
    check("lock remove deletes it, and again is not an error",
          task("lock", "remove", str(tree)).returncode == 0 and not lock.exists() and task("lock", "remove", str(tree)).returncode == 0)
    repo, record = tmp / "repo", tmp / "task"
    record.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    (record / "PROGRESS.md").write_text("", encoding="utf-8")

    def pref(*extra: str) -> str:
        return task("worktree", "pref", "--repo", str(repo), *extra).stdout.strip()

    marker = repo / ".git" / "crew-worktree"
    check("a repo that never answered gets `ask`", pref() == "ask")
    first = task("worktree", "record", "here", str(record), "--repo", str(repo))
    task("worktree", "record", "worktree", str(record), "--repo", str(repo))
    check("the first answer is recorded once, in the repo and in PROGRESS.md, and reused",
          first.returncode == 0 and marker.read_text().strip() == "here" and progress_text(record).count("WORKTREE: here") == 1 and pref() == "here")
    (repo / "AGENTS.md").write_text("# Repo\n\nworktree: true\n", encoding="utf-8")
    check("`worktree: true` in AGENTS.md wins, and --json names the source", pref() == "worktree" and '"source": "agents"' in pref("--json"))
    (repo / "AGENTS.md").write_text("# Repo\n\n```\nworktree: true\n```\n\nworktree: false\n", encoding="utf-8")
    check("`worktree: false` means here; a fenced line is ignored", pref() == "here")
    marker.unlink()
    (repo / "AGENTS.md").unlink()
    check("no setting and no record is `ask` again", pref() == "ask")
    check("an answer that is neither is refused", task("worktree", "record", "maybe", str(record), "--repo", str(repo)).returncode == 2)

    def tree_state(*extra: str) -> subprocess.CompletedProcess:
        return task("worktree", "check", str(repo), *extra)

    check("a clean default branch is `ok`, exit 0", (tree_state().stdout.strip(), tree_state().returncode) == ("ok", 0))
    (repo / "mine.txt").write_text("x", encoding="utf-8")
    check("an uncommitted file is `dirty`, exit 5", (tree_state().stdout.strip(), tree_state().returncode) == ("dirty", 5))
    (repo / "mine.txt").unlink()
    (repo / ".crew-worker.lock").write_text("task=T\n", encoding="utf-8")
    (repo / "tasks").mkdir()
    (repo / "tasks" / "SPEC.md").write_text("spec", encoding="utf-8")
    check("the lock and files under --task-dir are the task's own; without it they are dirty",
          tree_state("--task-dir", str(repo / "tasks")).returncode == 0 and tree_state().returncode == 5)
    shutil.rmtree(repo / "tasks")
    subprocess.run(["git", "-C", str(repo), "switch", "-q", "-c", "feat/x"], check=True)
    (repo / "wip.txt").write_text("x", encoding="utf-8")
    done = tree_state("--json")
    check("a non-default branch is used as-is, even when dirty: exit 4", done.returncode == 4 and '"state": "on-feature-branch"' in done.stdout)
    check("a path that is not a repo is exit 2", task("worktree", "check", str(tmp / "none")).returncode == 2)


GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
          "GIT_CONFIG_GLOBAL": os.devnull}


def test_crew_worktree_creates_lists_fetches_and_removes(tmp: Path) -> None:
    """`crew-worktree.py` against a local origin, `gh` failing like a blocked network so git answers."""
    origin, repo, bin_dir = tmp / "origin.git", tmp / "repo", tmp / "bin"
    env = {**os.environ, **GIT_ID}
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, env=env)
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, env=env, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "base"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", "HEAD:main"], check=True, env=env)
    bin_dir.mkdir()
    (bin_dir / "gh").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    run_env = {**GIT_ID, "HOME": str(tmp), "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

    def worktree(*arguments: str) -> subprocess.CompletedProcess:
        return cli(TASK_TOOLS / "crew-worktree.py", *arguments, env=run_env, cwd=repo)

    created = worktree("-b", "topic", "origin/main", "--json")
    path = Path(json.loads(created.stdout)["path"]) if created.returncode == 0 else Path()
    check("a new branch gets a worktree beside the checkout", path == (tmp / "worktrees" / "repo-topic").resolve(),
          created)
    check("asking again resolves the same worktree", json.loads(worktree("topic", "--json").stdout)["path"] == str(path))
    listed = json.loads(worktree("--list").stdout)
    check("--list reports it with its branch", any(entry["branch"] == "topic" for entry in listed["worktrees"]), listed)
    check("fetch refreshes the remote", worktree("fetch").stdout.strip() == "fetched origin")
    removed = worktree("--remove", str(path), "--branch", "topic")
    branch = subprocess.run(["git", "-C", str(repo), "branch", "--list", "topic"], capture_output=True, text=True)
    check("--remove deletes the worktree and its merged branch",
          removed.returncode == 0 and not path.exists() and not branch.stdout, removed)


VIEW_STUB = """#!/bin/sh
echo "$*" >> "$GH_CALLS"
[ "$1 $2" = "pr view" ] || exit 1
cat "$GH_VIEWS/${3##*/}" 2>/dev/null || exit 1
"""
# name: (status, repo, branch, spec_branch)
RECORD_TASKS = {"wt": ("IMPLEMENTING", "acme/widgets", "feat/wt", ""), "head": ("IMPLEMENTING", "acme/widgets", "feat/h", ""),
                "repo": ("IMPLEMENTING", "acme/widgets", "feat/r", ""), "fork": ("IMPLEMENTING", "me/widgets", "feat/f", ""),
                "collide": ("IMPLEMENTING", "acme/widgets", "feat/c", "feat/s"), "twin-a": ("IMPLEMENTING", "acme/widgets", "feat/two", ""),
                "twin-b": ("IMPLEMENTING", "acme/widgets", "feat/two", ""), "shipped": ("DONE", "acme/widgets", "feat/d", ""),
                "reuse-old": ("DONE", "acme/widgets", "feat/reuse", ""), "reuse-new": ("IMPLEMENTING", "acme/widgets", "feat/reuse", "")}
PR_NEW = "https://github.com/acme/widgets/pull/21"
OPEN_PR_COMMAND = ('PR_URL=$(GH_PAGER=cat gh pr create --draft --title "TITLE" --body "BODY" --base BASE --repo "$TARGET_REPO")'
                   ' && echo "$PR_URL"')  # crew-open-pr's own command, verbatim


def record_world(tmp: Path) -> tuple[Path, Path, dict]:
    """A HOME with crew-task.py, the tasks of RECORD_TASKS, a main checkout and a worktree on feat/wt, and a stub gh."""
    home, repo, env = tmp / "home", tmp / "checkout", {**os.environ, **GIT_ID}
    (home / ".agent" / "bin").mkdir(parents=True)
    (home / ".agent" / "bin" / "crew-task.py").symlink_to(TASK)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:acme/widgets.git"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "base"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feat/wt", str(tmp / "wt")], check=True, env=env, capture_output=True)
    subprocess.run(["git", "-C", str(tmp / "wt"), "commit", "-q", "--allow-empty", "-m", "work"], check=True, env=env)
    tip = subprocess.run(["git", "-C", str(tmp / "wt"), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    for name, (status, slug, branch, spec_branch) in RECORD_TASKS.items():
        directory = spec(home / ".agent" / "tasks" / name, status, review=f"Verdict: pass\n\nReviewed at: {tip}" if name == "wt" else None)
        meta = {"slug": name, "branch": branch, "repo_remote_url": f"git@github.com:{slug}.git", "created_at": "2026-01-01T00:00:00Z"}
        (directory / ".task-id").write_text(json.dumps({**meta, **({"spec_branch": spec_branch} if spec_branch else {})}), encoding="utf-8")
        if status == "DONE":
            (directory / "PROGRESS.md").write_text(f"[2026-01-01T00:00:00Z] TRANSITION: IMPLEMENTING → DONE (PR opened: {PR_ONE})\n", encoding="utf-8")
    (tmp / "bin").mkdir()
    (tmp / "bin" / "gh").write_text(VIEW_STUB, encoding="utf-8")
    (tmp / "bin" / "gh").chmod(0o755)
    (tmp / "views").mkdir()
    run_env = {**os.environ, **GIT_ID, "HOME": str(home), "PATH": f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
               "GH_CALLS": str(tmp / "calls"), "GH_VIEWS": str(tmp / "views")}
    return home, repo, run_env


def record_hook(tmp: Path, shape: str, command: str, output: str, branch: str, owner: str = "acme",
                break_task: str = "", prepare: Callable[[Path], None] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run record-pr.sh on one payload of the given harness shape, the PR's `gh pr view` answer being `branch` and `owner`;
    `break_task` turns that task's PROGRESS.md into a directory, so writing the PR fails; `prepare(tasks)` runs before the
    hook; `cwd` is the payload's cwd (default the main checkout)."""
    home, repo, env = record_world(tmp)
    if break_task:
        (home / ".agent" / "tasks" / break_task / "PROGRESS.md").unlink()
        (home / ".agent" / "tasks" / break_task / "PROGRESS.md").mkdir()
    if prepare:
        prepare(home / ".agent" / "tasks")
    view = {"headRefName": branch, "headRepositoryOwner": {"login": owner}, "headRepository": {"name": "widgets"}, "title": "Fix: the Widget's edge"}
    (tmp / "views" / "21").write_text(json.dumps(view), encoding="utf-8")
    where = str(cwd or repo)
    payload = ({"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": where, "tool_input": {"command": command},
                "tool_response": {"stdout": output, "stderr": ""}} if shape == "claude"
               else {"hook_event_name": "afterShellExecution", "cwd": where, "command": command, "output": output})
    hook = ROOT / ".claude" / "hooks" / "record-pr.sh"
    return subprocess.run(["bash", str(hook)], input=json.dumps(payload), capture_output=True, text=True, env=env, cwd=repo)


@pytest.mark.parametrize("label,shape,command,output,branch,owner,changed,words,asks", [
    ("main tree, worktree branch", "claude", "gh pr create --fill", PR_NEW, "feat/wt", "acme", {"wt": "DONE"}, "recorded PR", True),
    ("--head", "claude", "gh pr create --head feat/h --fill", f"Creating pull request\n{PR_NEW}\n", "feat/h", "acme", {"head": "DONE"},
     "applied: head -> DONE", True),
    ("-R", "cursor", "gh pr create -R acme/widgets --fill", PR_NEW, "feat/r", "acme", {"repo": "DONE"}, "applied: repo -> DONE", True),
    ("fork head", "claude", "cd x && gh pr create --repo acme/widgets", PR_NEW, "feat/f", "me", {"fork": "DONE"}, "applied: fork -> DONE", True),
    ("crew open pr's command", "claude", OPEN_PR_COMMAND, f"{PR_NEW}\n", "feat/h", "acme", {"head": "DONE"}, "applied: head -> DONE", True),
    ("a chained comment URL is not a PR URL", "claude", "gh pr create --fill && gh pr comment 21 --body hi",
     f"{PR_NEW}\n{PR_NEW}#issuecomment-123\n", "feat/h", "acme", {"head": "DONE"}, "applied: head -> DONE", True),
    ("two PR URLs", "claude", "gh pr create --fill && gh pr list", f"{PR_NEW}\nhttps://github.com/acme/widgets/pull/7\n", "feat/h", "acme", {},
     "the output holds 2 PR URLs", False),
    ("echoed text", "claude", f"echo gh pr create would open {PR_NEW}", PR_NEW, "feat/h", "acme", {}, "", False),
    ("spec_branch collision", "claude", "gh pr create --fill", PR_NEW, "feat/s", "acme", {}, "feat/s is the spec branch of collide", True),
    ("DONE match", "claude", "gh pr create --fill", PR_NEW, "feat/d", "acme", {"shipped": "DONE"}, "shipped (DONE): recorded PR", True),
    ("reused branch: the open task wins", "claude", "gh pr create --fill", PR_NEW, "feat/reuse", "acme", {"reuse-new": "DONE"},
     "applied: reuse-new -> DONE", True),
    ("two matches", "claude", "gh pr create --fill", PR_NEW, "feat/two", "acme", {}, f"crew-task.py mark-done {{tasks}}/twin-a --pr-url {PR_NEW}", True),
    ("failed create", "claude", "gh pr create --fill", "pull request create failed: GraphQL: No commits", "feat/h", "acme", {}, "", False),
    ("unrelated command", "claude", "git log --oneline", f"see {PR_NEW}", "feat/h", "acme", {}, "", False),
])
def test_record_pr_hook(tmp: Path, label: str, shape: str, command: str, output: str, branch: str, owner: str, changed: dict, words: str,
                        asks: bool) -> None:
    """The PR hook acts only on a real `gh pr create` segment with exactly one PR URL in its output, finds the task from
    `gh pr view` (repo or fork, `branch` only, the open match first), closes an IMPLEMENTING match, appends to a DONE one,
    records nothing for two or for a spec branch, and never asks gh otherwise; every other task stays as it was."""
    done = record_hook(tmp, shape, command, output, branch, owner)
    tasks = tmp / "home" / ".agent" / "tasks"
    for name, (status, *_) in RECORD_TASKS.items():
        before = [PR_ONE] if status == "DONE" else []
        expected = (changed[name], before + [PR_NEW]) if name in changed else (status, before)
        got = (status_of(tasks / name), task_state.load(tasks / name).prs)
        check(f"{label}: {name}", got == expected, (got, expected, done.stdout))
    check(f"{label}: no task created", {path.name for path in tasks.iterdir()} == set(RECORD_TASKS))
    calls = (tmp / "calls").read_text().splitlines() if (tmp / "calls").exists() else []
    check(f"{label}: exit 0, the outcome in the hook output, gh asked only about a created PR",
          done.returncode == 0 and words.replace("{tasks}", str(tasks)) in done.stdout and (bool(words) or done.stdout == "")
          and bool(calls) is asks, (done.stdout, done.stderr, calls))
    if shape == "claude" and words:
        check(f"{label}: Claude reads it as additional context", json.loads(done.stdout)["hookSpecificOutput"]["hookEventName"] == "PostToolUse")


@pytest.mark.parametrize("url,owner,created", [(PR_NEW, "acme", True), ("https://github.com/other/thing/pull/21", "other", False)])
def test_record_pr_with_no_task(tmp: Path, url: str, owner: str, created: bool) -> None:
    """A PR no task matches becomes a minimal DONE task only in a repo that already has tasks; `crew ls` lists it with its PR."""
    done = record_hook(tmp, "claude", "gh pr create --fill", url, "feat/new", owner)
    tasks = tmp / "home" / ".agent" / "tasks"
    new = sorted({path.name for path in tasks.iterdir()} - set(RECORD_TASKS))
    check("exit 0; a directory only for the repo in scope", done.returncode == 0 and len(new) == int(created), (new, done.stdout, done.stderr))
    if not created:
        return
    listed = cli(LS, "--tasks-dir", str(tasks), "--all", "--json", "--repo", "all", env={"PATH": f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}"})
    row = next(item for item in json.loads(listed.stdout)["items"] if item["directory"] == str(tasks / new[0]))
    check("the new task is DONE with its PR, the head branch, the repo and a slug from the title",
          (row["state"], row["prs"], row["branch"], row["repo"], row["slug"]) == ("DONE", [url], "feat/new", "acme/widgets", "fix-the-widget-s-edge"),
          row)


def test_record_pr_reports_a_failure_in_one_line(tmp: Path) -> None:
    """A write that fails is one `record-pr: nothing recorded` line in the hook output, never a traceback; exit 0."""
    done = record_hook(tmp, "cursor", "gh pr create --fill", PR_NEW, "feat/h", break_task="head")
    check("one record-pr line names the failure", done.returncode == 0 and "record-pr: nothing recorded:" in done.stdout
          and "Traceback" not in done.stdout and status_of(tmp / "home" / ".agent" / "tasks" / "head") == "IMPLEMENTING", (done.stdout, done.stderr))


def extra_tasks(*rows: tuple[str, str, str, str, bool]) -> Callable[[Path], None]:
    """A `prepare` that adds tasks of acme/widgets: (name, status, `.task-id` branch, SPEC.md `## Branch:` with a CRLF ending,
    whether PR_NEW is already in its PR list)."""
    def prepare(tasks: Path) -> None:
        for name, status, branch, spec_branch, holds in rows:
            directory = spec(tasks / name, status, extra=f"## Branch: {spec_branch}\r\n\n")
            meta = {"slug": name, "branch": branch, "repo_remote_url": "git@github.com:acme/widgets.git"}
            (directory / ".task-id").write_text(json.dumps(meta), encoding="utf-8")
            if holds:
                (directory / "PROGRESS.md").write_text(f"[2026-01-01T00:00:00Z] PR: {PR_NEW}\n", encoding="utf-8")
                record_status(directory, status)
    return prepare


# label, extra tasks, head branch, the status and .task-id branch each extra task ends with, words, new directories
@pytest.mark.parametrize("label,rows,branch,after,words,created", [
    ("a task already holds the PR", [("holder", "DONE", "feat/other", "feat/other", True)], "feat/new", {"holder": ("DONE", "feat/other")},
     "holder (DONE): already has", 0),
    ("an IMPLEMENTING holder runs the gate", [("holder", "IMPLEMENTING", "feat/other", "feat/other", True)], "feat/new",
     {"holder": ("DONE", "feat/other")}, "applied: holder -> DONE", 0),
    ("the #35 order, hook first: the spec names the branch", [("late", "IMPLEMENTING", "main", "feat/late", False)], "feat/late",
     {"late": ("DONE", "feat/late")}, "applied: late -> DONE", 0),
    ("two specs name it", [("late-a", "IMPLEMENTING", "main", "feat/late", False), ("late-b", "IMPLEMENTING", "main", "feat/late", False)],
     "feat/late", {"late-a": ("IMPLEMENTING", "main"), "late-b": ("IMPLEMENTING", "main")}, "2 tasks name feat/late in their spec", 0),
    ("a draft and an approved spec are never matched",
     [("draft", "DRAFTING", "main", "feat/late", False), ("ok", "APPROVED", "main", "feat/late", False)],
     "feat/late", {"draft": ("DRAFTING", "main"), "ok": ("APPROVED", "main")}, "no task for feat/late", 1),
    ("a task started on another branch is never matched by its spec", [("moved", "IMPLEMENTING", "feat/real", "feat/late", False)],
     "feat/late", {"moved": ("IMPLEMENTING", "feat/real")}, "no task for feat/late", 1),
])
def test_record_pr_without_a_branch_match(tmp: Path, label: str, rows: list, branch: str, after: dict, words: str, created: int) -> None:
    """A task holding the URL is the match; else the single IMPLEMENTING task whose SPEC.md `## Branch:` is the head branch,
    its `.task-id` branch updated; DRAFTING and APPROVED specs are never matched that way."""
    done = record_hook(tmp, "cursor", "gh pr create --fill", PR_NEW, branch, prepare=extra_tasks(*rows))
    tasks = tmp / "home" / ".agent" / "tasks"
    got = {name: (status_of(tasks / name), json.loads((tasks / name / ".task-id").read_text())["branch"]) for name in after}
    new = {path.name for path in tasks.iterdir()} - set(RECORD_TASKS) - set(after)
    check(f"{label}: statuses, branches, output and new directories", (got, words in done.stdout, len(new)) == (after, True, created),
          (got, done.stdout, new))
    if label.startswith("the #35"):
        meta = json.loads((tasks / "late" / ".task-id").read_text())
        check("the drafting branch is kept and the PR recorded once", meta["spec_branch"] == "main" and task_state.load(tasks / "late").prs == [PR_NEW],
              meta)


# the recorded worktree ("" for none), the payload cwd, and whether the DONE gate passes
@pytest.mark.parametrize("label,recorded,cwd,passes", [
    ("the task's worktree, the hook in another repository", "wt", "unrelated", True),
    ("a stale worktree on another branch: its repository's worktrees", "checkout", "unrelated", True),
    ("a deleted path falls through to the cwd", "gone", "checkout", True),
    ("nothing found", "", "unrelated", False),
    ("a reused path: another repository on the branch is not trusted", "foreign", "checkout", True),
])
def test_record_pr_runs_the_gate_from_the_task_checkout(tmp: Path, label: str, recorded: str, cwd: str, passes: bool) -> None:
    """`branch_tree`: the task's `worktree` when it is still the task's repository and holds the branch, else that
    repository's worktrees, else the cwd's; when none has it, the gate's error and the retry line."""
    env = {**os.environ, **GIT_ID}
    for name, branch in (("unrelated", "main"), ("foreign", "feat/wt")):
        subprocess.run(["git", "init", "-q", "-b", branch, str(tmp / name)], check=True, env=env)
        subprocess.run(["git", "-C", str(tmp / name), "commit", "-q", "--allow-empty", "-m", "x"], check=True, env=env)

    def prepare(tasks: Path) -> None:
        if recorded:
            meta = json.loads((tasks / "wt" / ".task-id").read_text())
            (tasks / "wt" / ".task-id").write_text(json.dumps({**meta, "worktree": str(tmp / recorded)}), encoding="utf-8")

    done = record_hook(tmp, "cursor", "gh pr create --fill", PR_NEW, "feat/wt", prepare=prepare, cwd=tmp / cwd)
    status = status_of(tmp / "home" / ".agent" / "tasks" / "wt")
    expected = ("DONE", "applied: wt -> DONE") if passes else ("IMPLEMENTING", "stays IMPLEMENTING; after fixing it run:")
    check(label, (status, expected[1] in done.stdout) == (expected[0], True), done.stdout)


USAGE_ONE = {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 20000, "cache_creation_input_tokens": 3000}
USAGE_TWO = {"input_tokens": 10, "output_tokens": 2600, "cache_read_input_tokens": 40000, "cache_creation_input_tokens": 0}


def usage_world(tmp: Path) -> tuple[Path, Path]:
    """A HOME with crew-review-findings.py and one IMPLEMENTING task `built` whose implement stage has started."""
    home, tasks = tmp / "home", tmp / "home" / ".agent" / "tasks"
    (home / ".agent" / "bin").mkdir(parents=True)
    (home / ".agent" / "bin" / "crew-review-findings.py").symlink_to(REVIEW_TOOLS / "crew-review-findings.py")
    task_dir = spec(tasks / "built", "IMPLEMENTING")
    (task_dir / "PROGRESS.md").write_text("[2026-11-27T10:00:00Z] METRIC: stage_start stage=implement\n", encoding="utf-8")
    return home, task_dir


def stop(tmp: Path, home: Path, prompt: str, calls: list, usage: bool = True) -> subprocess.CompletedProcess:
    """One SubagentStop of agent a1 over a transcript of `prompt` and `calls` (`(message id, usage)` pairs)."""
    turns = [{"type": "user", "message": {"role": "user", "content": prompt}}]
    for message_id, counts in calls:
        message = {"id": message_id, "role": "assistant", "model": "m-1", "content": [{"type": "text", "text": "ok"}]}
        turns.append({"type": "assistant", "message": {**message, **({"usage": counts} if usage else {})}})
    transcript = tmp / "agent.jsonl"
    transcript.write_text("".join(json.dumps(turn) + "\n" for turn in turns), encoding="utf-8")
    payload = {"hook_event_name": "SubagentStop", "agent_id": "a1", "agent_type": "crew-builder", "agent_transcript_path": str(transcript),
               "last_assistant_message": "report: done"}
    hook = ROOT / ".claude" / "hooks" / "capture-reply.sh"
    return subprocess.run(["bash", str(hook)], input=json.dumps(payload), capture_output=True, text=True, env={**os.environ, "HOME": str(home)})


@pytest.mark.parametrize("case", ["builder", "no marker", "no usage", "outside the tasks directory"])
def test_agent_end_recorded_by_the_subagent_stop_hook(tmp: Path, case: str) -> None:
    """The SubagentStop hook writes one `agent_end` on the task its `crew-task:` line names: `tokens` is the LAST call's
    context (what the harness reports), never the sum of every call's cache reads; input, output, cache_read and
    cache_write are summed (a message repeated per content block counts once). `crew ls --cost` and `--report` show
    `tokens` with the summed output beside it, per task: a task with only `tokens_reported` in the same stage keeps it.
    No marker, no usage field, or a named directory outside `~/.agent/tasks` records nothing."""
    home, task_dir = usage_world(tmp)
    outside = spec(tmp / "outside", "IMPLEMENTING")
    named = {"no marker": "", "outside the tasks directory": f"crew-task: {outside}\n"}.get(case, f"crew-task: {task_dir}\n")
    done = stop(tmp, home, named + "TASK_DIR: x\nImplement T1.", [("m1", USAGE_ONE), ("m1", USAGE_ONE), ("m2", USAGE_TWO)], case != "no usage")
    ends = [line for line in progress_text(task_dir).splitlines() + progress_text(outside).splitlines() if "agent_end" in line]
    check(f"{case}: exit 0", done.returncode == 0, (done.stdout, done.stderr))
    if case != "builder":
        check(f"{case}: nothing recorded", ends == [], (ends, done.stdout))
        return
    context = sum(USAGE_TWO.values())  # 42,610: the last call; the sum over calls would be 66,110
    check("one agent_end: the last call's context as tokens, the summed counts beside it", len(ends) == 1 and ends[0].endswith(
        f"METRIC: agent_end agent=crew-builder persona=crew-builder agent_id=a1 tokens={context} input=1010 output=3100 cache_read=60000 "
        "cache_write=3000"), (ends, done.stdout))
    other = spec(task_dir.parent / "cursor", "IMPLEMENTING")
    (other / "PROGRESS.md").write_text("[2026-11-27T10:00:00Z] METRIC: stage_start stage=implement\n"
                                       "[2026-11-27T11:00:00Z] METRIC: stage_end stage=implement workers=1 tokens_reported=5000\n", encoding="utf-8")
    cost = cli(LS, "--tasks-dir", str(task_dir.parent), "--cost").stdout
    check("crew ls --cost shows the new tokens (input + output + cache_write, 7k) and cache reads, the other task its report",
          "built: new 7k, cache reads 60k; implement: 1 workers, new 7k" in cost
          and "cursor: new ~5k, cache reads -; implement: 1 workers, new ~5k" in cost, cost)
    report = cli(LS, "--tasks-dir", str(task_dir.parent), "--report", "--since", "36500d", "--repo", "all", env={"HOME": str(home)}).stdout
    check("crew report applies the replacement per task: 7k + ~5k in one stage, and the agent apart",
          "stage implement: 1 run(s), new ~12k, cache reads 60k, from 1 agent(s)" in report
          and "agent crew-builder: 1 run(s), new 7k, cache reads 60k" in report, report)


def test_agent_end_counts_a_resumed_agent_once(tmp: Path) -> None:
    """Three stops of one resumed agent on one growing transcript write three entries; only the latest counts."""
    home, task_dir = usage_world(tmp)
    calls = []
    for number in range(1, 4):
        calls.append((f"m{number}", {"input_tokens": 1000 * number, "output_tokens": 1000, "cache_read_input_tokens": 0,
                                     "cache_creation_input_tokens": 0}))
        check(f"stop {number}", stop(tmp, home, f"crew-task: {task_dir}\nImplement.", calls).returncode == 0)
    ends = [line for line in progress_text(task_dir).splitlines() if "agent_end" in line]
    cost = cli(LS, "--tasks-dir", str(task_dir.parent), "--cost").stdout
    report = cli(LS, "--tasks-dir", str(task_dir.parent), "--report", "--since", "36500d", "--repo", "all", env={"HOME": str(home)}).stdout
    check("three entries, counted as one agent: the latest stop's new tokens (6k input + 3k output)",
          len(ends) == 3 and "built: new 9k, cache reads 0; implement: 1 workers, new 9k" in cost
          and "stage implement: new 9k, cache reads 0, from 1 agent(s)" in report, (ends, cost, report))


def test_crew_resolve_task_dir_prefers_the_open_task(tmp: Path) -> None:
    """Two tasks on one repo and branch: the open one wins over a newer DONE one, and `--all` lists both."""
    remote, tasks = "git@example.invalid:owner/demo.git", tmp / ".agent" / "tasks"
    for name, status, month in (("open", "IMPLEMENTING", "01"), ("shipped", "DONE", "02")):
        directory = spec(tasks / name, status)
        (directory / ".task-id").write_text(json.dumps({"repo_remote_url": remote, "branch": "feat", "slug": name,
                                                        "created_at": f"2026-{month}-01T00:00:00Z"}), encoding="utf-8")

    def resolve(branch: str, *arguments: str) -> subprocess.CompletedProcess:
        return cli(TASK_TOOLS / "crew-resolve-task-dir.py", "--remote", remote, "--branch", branch, *arguments,
                   env={"HOME": str(tmp)})

    best = resolve("feat", "--json")
    record = json.loads(best.stdout)
    check("the most recent non-DONE task is chosen, and the choice is said",
          record["slug"] == "open" and record["has_spec"] and "Multiple tasks" in best.stderr, (best.stdout, best.stderr))
    every = json.loads(resolve("feat", "--all", "--json").stdout)
    check("--all lists every match with its status",
          sorted(m["status"] for m in every["matches"]) == ["DONE", "IMPLEMENTING"], every)
    check("no match prints an empty line", resolve("other").stdout == "\n")


def tree(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*")}


def test_gc_dry_run_then_apply(tmp: Path) -> None:
    """`crew-task.py gc` selects by the policy (config.json overrides a default), a dry run changes nothing,
    and `--apply` removes exactly the selected paths, archiving the old DONE task into a tarball. A task a
    worker holds, one with a file newer than its PROGRESS, and a `.sessions` that is a link are left alone."""
    agent, now = tmp / ".agent", time.time()
    for name, status, days, extra in (("ancient", "DONE", 100, None), ("recent", "DONE", 12, None), ("fresh", "DONE", 5, None),
                                      ("stalled", "IMPLEMENTING", 200, None), ("locked", "DONE", 100, ".crew-worker.lock"),
                                      ("reviewed", "DONE", 100, "REVIEW.md")):
        directory = spec(agent / "tasks" / name, status)
        (directory / "artifacts").mkdir()
        (directory / "artifacts" / "log.txt").write_text("x", encoding="utf-8")
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - days * 86400))
        (directory / "PROGRESS.md").write_text(f"[{stamp}] TRANSITION: IMPLEMENTING → {status}\n", encoding="utf-8")
        for path in [*directory.rglob("*"), directory]:
            os.utime(path, (now - days * 86400,) * 2)
        if extra:
            (directory / extra).write_text("task=x\n", encoding="utf-8")
    sessions = agent / "memory" / ".sessions"
    sessions.mkdir(parents=True)
    for name in ("old.jsonl", "new.jsonl", "review-queue.jsonl"):
        (sessions / name).write_text("{}\n", encoding="utf-8")
        if name != "new.jsonl":
            os.utime(sessions / name, (now - 40 * 86400,) * 2)
    (agent / "telemetry").mkdir()
    (agent / "telemetry" / "raw.jsonl").write_text('{"command": "x"}\n', encoding="utf-8")
    (agent / "config.json").write_text(json.dumps({"gc": {"artifacts_days": 10}}), encoding="utf-8")
    env = {"HOME": str(tmp), "CREW_MEMORY_DIR": None}
    before = tree(agent)
    planned = cli(TASK, "gc", "--json", env=env)
    selected = {(a["verb"], Path(a["path"]).relative_to(agent).as_posix()) for a in json.loads(planned.stdout)}
    check("the dry run selects old DONE artifacts (config: 10 days), the 90-day DONE task, old session files and telemetry",
          selected == {("remove", "tasks/ancient/artifacts"), ("remove", "tasks/recent/artifacts"), ("archive", "tasks/ancient"),
                       ("remove", "memory/.sessions/old.jsonl"), ("remove", "telemetry")} and tree(agent) == before, planned)
    only = json.loads(cli(TASK, "gc", "--only", "telemetry", "--json", env=env).stdout)
    check("--only telemetry selects the telemetry alone", [a["path"] for a in only] == [str(agent / "telemetry")], only)
    applied = cli(TASK, "gc", "--apply", "--json", env=env)

    def outermost(paths: set[str]) -> set[str]:
        return {path for path in paths if not any(path.startswith(top + "/") for top in paths)}

    gone, archive = outermost(before - tree(agent)), list((agent / "archive").glob("tasks-*.tar.gz"))
    archived = [a.get("archive") for a in json.loads(applied.stdout) if a["verb"] == "archive"]
    check("--apply removes exactly the selected paths and archives the old task; --json names the tarball",
          applied.returncode == 0 and gone == outermost({p for _, p in selected}) and len(archive) == 1
          and "ancient/SPEC.md" in tarfile.open(archive[0]).getnames() and archived == [str(archive[0])],
          (applied.stdout, applied.stderr, gone))
    outside = tmp / "outside"
    outside.mkdir()
    (outside / "notes.txt").write_text("mine\n", encoding="utf-8")
    os.utime(outside / "notes.txt", (now - 400 * 86400,) * 2)
    shutil.rmtree(sessions)
    sessions.symlink_to(outside)
    linked = cli(TASK, "gc", "--apply", env=env)
    check("a .sessions that is a link is skipped with a note, its files kept",
          (outside / "notes.txt").exists() and "skipped ~/.agent/memory/.sessions" in linked.stdout, linked.stdout)
    for bad in ({"gc": {"artifact_days": 1}}, {"ls": {"repo": "not a repo"}}, {"ls": {"repo": 3}}):
        (agent / "config.json").write_text(json.dumps(bad), encoding="utf-8")
        check(f"{bad}: gc and crew ls refuse with exit 2", (cli(TASK, "gc", env=env).returncode, cli(LS, env=env).returncode) == (2, 2))
