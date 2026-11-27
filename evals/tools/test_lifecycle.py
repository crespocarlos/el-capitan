#!/usr/bin/env python3
"""A task's life through `crew-task.py`: the status contract, the gates, reconcile, the close-out, the lock.

`## Status` holds one token per state and the migration settles legacy spellings once. Gate 1
(`mark-approved`) and Gate 2 (`mark-done`) refuse what they must and write one PROGRESS line when they
pass; `reconcile --apply` holds idle specs and reports its write failures in its exit code; the
session-start hook prints what reconcile did. A PR-mode review persists outside the task, so the
close-out gate must find it there and read its verdict and `Reviewed at:` from the same file. The
worker lock and the once-per-repo worktree choice round-trip on a real repository. Every command runs
in this process through `cli_runner`; the hook runs under bash.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from cli_runner import run as cli

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


def check(name: str, condition: bool, detail: object = "") -> None:
    assert condition, f"{name}: {detail}"


def task(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return cli(TASK, *arguments, cwd=cwd)


def ls(tasks: Path, *arguments: str) -> str:
    return cli(LS, "--tasks-dir", str(tasks), *arguments).stdout


def spec(directory: Path, status: str, boxes: str = "- [x] a", review: str | None = None, old: bool = False, extra: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SPEC.md").write_text(f"# T\n\n## Status\n{status}\n\n{extra}{boxes}\n", encoding="utf-8")
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
    check("crew ls prints the STATE TASK BRANCH REVIEW AGE table", table[:1] and table[0].split() == ["STATE", "TASK", "BRANCH", "REVIEW", "AGE"], table[:1])
    check("--md prints the same columns as a table", "| STATE | TASK | BRANCH | REVIEW | AGE |\n|---|---|---|---|---|" in ls(tasks, "--md"))
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
          refuses(task("mark-implementing", str(tasks / "missing")), "no SPEC.md") and refuses(task("mark-done", str(tasks / "missing"), "--pr-url", "x"), "no SPEC.md"))
    approved = spec(tasks / "approved", "APPROVED", review="Verdict: warn")
    task("mark-implementing", str(approved))
    check("APPROVED → IMPLEMENTING is written and logged", status_of(approved) == "IMPLEMENTING" and "APPROVED → IMPLEMENTING" in progress_text(approved))
    check("a second mark-implementing says already implementing", "already implementing" in task("mark-implementing", str(approved)).stdout)
    branch = spec(tasks / "branch", "IMPLEMENTING", review="Verdict: pass")
    (branch / ".task-id").write_text('{"slug":"branch","branch":"feature/x"}', encoding="utf-8")
    check("mark-done refuses another branch", refuses(task("mark-done", str(branch), "--pr-url", "x", "--branch", "feature/y"), "current branch is feature/y")
          and status_of(branch) == "IMPLEMENTING")
    task("mark-done", str(branch), "--pr-url", "https://example.test/pr/1", "--branch", "feature/x")
    check("IMPLEMENTING → DONE is written with the PR", status_of(branch) == "DONE"
          and "IMPLEMENTING → DONE (PR opened: https://example.test/pr/1)" in progress_text(branch))
    check("a second mark-done says already done", "already done" in task("mark-done", str(branch), "--pr-url", "x").stdout)
    refusals = (
        ("unchecked", spec(tasks / "open", "IMPLEMENTING", "- [ ] a", "Verdict: pass"), ("--pr-url", "x")),
        ("need pass or warn", spec(tasks / "rerun", "IMPLEMENTING", review="Verdict: pass\n\nVerdict: BLOCK"), ("--pr-url", "x")),
        ("not IMPLEMENTING", tasks / "draft", ("--pr-url", "x")),
        ("--pr-url", tasks / "draft", ()),
        ("cannot verify that review", spec(tasks / "unknown-sha", "IMPLEMENTING", review="Verdict: pass\n\nReviewed at: " + "0123456789abcdef" * 2 + "01234567"),
         ("--pr-url", "x", "--branch", "main")),
    )
    for words, directory, extra in refusals:
        before = status_of(directory)
        check(f"mark-done refuses: {words}", refuses(task("mark-done", str(directory), *extra), words) and status_of(directory) == before)
    task("mark-done", str(tasks / "open"), "--pr-url", "x", "--force")
    check("--force closes an unchecked task", status_of(tasks / "open") == "DONE")
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    ancestor = spec(tasks / "ancestor", "IMPLEMENTING", review=f"Verdict: pass\n\nReviewed at: {head}")
    task("mark-done", str(ancestor), "--pr-url", "x", "--branch", "main", cwd=ROOT)
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
    hook = ROOT / ".claude" / "hooks" / "spec-status-reconcile.sh"
    out = subprocess.run(["bash", str(hook)], capture_output=True, text=True, env={**os.environ, "HOME": str(home)}).stdout
    check("the hook reports the hold, the unreviewed done, the ready and the stalled task",
          all(line in out for line in ("spec-status: idle -> ON-HOLD", "1 done spec(s) lack a review pass", "spec-status: 1 ready to open PR: ready",
                                       "spec-status: 1 stalled IMPLEMENTING: stuck")), out)
    missing = subprocess.run(["bash", str(hook)], capture_output=True, text=True, env={**os.environ, "HOME": str(tmp / "no-tool")}).stdout
    check("a missing tool is reported with the fix", "crew-task.py missing; re-run install.sh" in missing, missing)


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
    return task("mark-done", str(directory), "--pr-url", "https://example.test/pr/1")


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
    temp_review(tmp / "refuse", "Verdict: BLOCK\n", refuse)
    done = close(refuse)
    check("a blocking temp review refuses with the verdict and where it was read", done.returncode == 1
          and "review verdict is BLOCK, need pass or warn" in done.stderr and "review read from" in done.stderr and status_of(refuse) == "IMPLEMENTING")
    done = close(make_task(tmp / "missing"))
    check("no review refuses: unknown verdict, none found", done.returncode == 1 and "review verdict is ?" in done.stderr and "no review found" in done.stderr)
    local = make_task(tmp / "local", "Verdict: pass\n")
    temp_review(tmp / "local", "Verdict: BLOCK\n", local)
    done = close(local)
    check("the review beside the spec wins over the recorded one", done.returncode == 0 and f"review read from {local / 'REVIEW.md'}" in done.stdout)
    stale = make_task(tmp / "stale")
    shutil.rmtree(temp_review(tmp / "stale", "Verdict: pass\n", stale))
    done = close(stale)
    check("a deleted review directory is no review", done.returncode == 1 and "no review found" in done.stderr)
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


def test_blocked_events(tmp: Path) -> None:
    """An autopilot stop writes one BLOCKED line that `crew ls` shows until the next stage starts."""
    tasks = tmp / "blocked-tasks"
    directory = make_task(tasks)
    written = task("blocked", str(directory), "stacked base: #51 is not main\nsecond line")
    lines = progress_text(directory).splitlines()
    check("blocked writes one BLOCKED line", written.returncode == 0 and len(lines) == 1
          and "BLOCKED: stacked base: #51 is not main second line" in lines[0], lines)
    rows = json.loads(ls(tasks, "--json") or "[]")
    check("crew ls and --json show the reason", "BLOCKED: stacked base: #51 is not main" in ls(tasks)
          and rows and rows[0].get("blocked", "").startswith("stacked base"), rows)
    cli(TASK_TOOLS / "crew-progress.py", str(directory), "IMPLEMENTING → IMPLEMENTING")
    check("the next stage clears it", "BLOCKED" not in ls(tasks) and json.loads(ls(tasks, "--json"))[0].get("blocked") == "")
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
