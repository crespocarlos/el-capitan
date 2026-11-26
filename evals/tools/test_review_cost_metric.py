#!/usr/bin/env python3
"""The cost line a persisted review records: what the run cost, and where it went.

Nothing recorded what a review spent, so a change to the package layout could not be compared
against the run it replaced. `persist` now appends one `METRIC:` line through `task_progress`: the
input and reply bytes, the persona count, the length of the byte prefix every package shares, and
whether a layer map was available. This suite pins the numbers against the files they come from, and
pins the run that must write nothing — a PR review with no task directory at all.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / ".agent" / "tools" / "review" / "crew-review-findings.py"
PERSONAS = ("adversarial", "architecture")


def review_dir(tmp: Path, packages: dict[str, str], name: str = "20260101000000") -> Path:
    directory = tmp / "task" / "review" / name
    directory.mkdir(parents=True)
    for persona, text in packages.items():
        (directory / f"{persona}.in.md").write_text(text, encoding="utf-8")
        (directory / f"{persona}.out.md").write_text("### Findings: none\n", encoding="utf-8")
    return directory


def persist(directory: Path, tmp: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    report = tmp / "report.md"
    report.write_text("## Review: changes\n\nVerdict: PASS\n", encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(TOOL), "persist", "--review-dir", str(directory),
         "--report", str(report), "--files", "a.ts", "--personas", *PERSONAS, *(extra or [])],
        capture_output=True, text=True)


def task(tmp: Path, packages: dict[str, str] | None = None) -> Path:
    """A task directory carrying SPEC.md and one packaged run inside it."""
    owner = tmp / "task"
    directory = review_dir(tmp, packages or {"adversarial": "SHARED\ntail a\n",
                                             "architecture": "SHARED\ntail b\n"})
    (owner / "SPEC.md").write_text("# Spec: something\n\n## Summary\n\ntext\n", encoding="utf-8")
    (owner / "PROGRESS.md").write_text("# Progress\n", encoding="utf-8")
    return directory


def metric_lines(owner: Path) -> list[str]:
    return [line for line in (owner / "PROGRESS.md").read_text(encoding="utf-8").splitlines()
            if "METRIC: review " in line]


def test_a_persisted_review_records_one_metric_line(tmp: Path) -> None:
    directory = task(tmp)
    result = persist(directory, tmp)
    assert result.returncode == 0, result.stderr
    lines = metric_lines(tmp / "task")
    assert len(lines) == 1, lines
    assert "review run=" in lines[0] and "in_bytes=" in lines[0] and "mapped=" in lines[0], lines[0]


def test_the_recorded_numbers_are_the_files_they_come_from(tmp: Path) -> None:
    """Input, reply, persona count, shared prefix, and the map flag are measured, not estimated."""
    directory = task(tmp, {"adversarial": "ZZZ COMMON\nadversarial tail\n",
                           "architecture": "AAA COMMON\narchitecture tail\n"})
    assert persist(directory, tmp).returncode == 0
    line = metric_lines(tmp / "task")[0]
    in_bytes = sum((directory / f"{p}.in.md").stat().st_size for p in PERSONAS)
    out_bytes = sum((directory / f"{p}.out.md").stat().st_size for p in PERSONAS)
    assert f"in_bytes={in_bytes} " in line, line
    assert f"out_bytes={out_bytes} " in line, line
    assert "personas=2 " in line, line
    assert "shared_prefix=0 " in line, "the first byte already differs, so nothing is shared"
    assert "mapped=0" in line, line


def test_a_run_with_a_layer_map_records_mapped_one(tmp: Path) -> None:
    """The flag reports whether a map existed, which is the fact a later comparison needs."""
    directory = task(tmp, {"adversarial": "COMMON HEAD\nA\n", "architecture": "COMMON HEAD\nB\n"})
    (directory / "layers.json").write_text(json.dumps({"layers": []}), encoding="utf-8")
    result = persist(directory, tmp, ["--lenient"])
    assert result.returncode == 0, result.stderr
    line = metric_lines(tmp / "task")[0]
    assert "mapped=1" in line, line
    # A package set that really does share a head records its length, not more and not less.
    assert "shared_prefix=12 " in line, line


def test_an_unmapped_run_records_mapped_zero(tmp: Path) -> None:
    directory = task(tmp)
    assert persist(directory, tmp).returncode == 0
    assert "mapped=0" in metric_lines(tmp / "task")[0]


def test_a_run_with_no_task_directory_writes_no_line_and_still_exits_zero(tmp: Path) -> None:
    """A PR review persists outside task state; telemetry must not turn that into a failure."""
    directory = review_dir(tmp, {"adversarial": "A\n", "architecture": "B\n"})
    result = persist(directory, tmp, ["--mode", "pr", "--head", "0123456789abcdef0123456789ab"])
    assert result.returncode == 0, result.stderr
    assert not (tmp / "task" / "PROGRESS.md").exists()
    assert "warning: cost metric" not in result.stderr, result.stderr


def test_a_task_directory_is_recognised_by_its_id_alone(tmp: Path) -> None:
    """`.task-id` marks a task as surely as SPEC.md does, and older tasks carry only that."""
    directory = task(tmp)
    (tmp / "task" / "SPEC.md").unlink()
    (tmp / "task" / ".task-id").write_text('{"slug": "something"}\n', encoding="utf-8")
    assert persist(directory, tmp).returncode == 0
    assert len(metric_lines(tmp / "task")) == 1


def test_a_failing_metric_writer_does_not_fail_the_persistence(tmp: Path) -> None:
    """The review is written before telemetry; a metric failure is reported, never raised."""
    sys.path[:0] = [str(ROOT / ".agent" / "tools" / "review")]
    import review_records

    def failing_writer(owner: Path, payload: str) -> None:
        raise OSError("PROGRESS.md is not writable")

    directory = task(tmp)
    original = review_records.append_metric
    review_records.append_metric = failing_writer
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            payload = review_records.record_cost(tmp / "task", directory, False)
    finally:
        review_records.append_metric = original
    assert payload.startswith("review run=") and "in_bytes=" in payload, payload
    assert "warning: cost metric not recorded" in stderr.getvalue(), stderr.getvalue()


METRIC_CLI = ROOT / ".agent" / "tools" / "task" / "crew-metric.py"
LS_CLI = ROOT / ".agent" / "tools" / "task" / "crew-ls.py"


def metric(owner: Path, *words: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(METRIC_CLI), str(owner), *words], capture_output=True, text=True)


def test_stage_keys_parse_and_stage_end_prints_the_cost_line(tmp: Path) -> None:
    (tmp / "PROGRESS.md").write_text("# Progress\n", encoding="utf-8")
    assert metric(tmp, "stage_start", "stage=implement").returncode == 0
    done = metric(tmp, "stage_end", "stage=implement", "workers=3", "tokens_reported=410000")
    assert done.returncode == 0 and done.stdout.strip() == "implement: 3 workers, 410k tokens", done
    review = metric(tmp, "stage_end", "stage=review", "personas=4", "tokens_reported=unknown")
    assert review.stdout.strip() == "review: 4 personas, tokens unknown", review.stdout
    lines = (tmp / "PROGRESS.md").read_text(encoding="utf-8")
    assert "METRIC: stage_start stage=implement" in lines and "tokens_reported=unknown" in lines, lines


def test_stage_keys_refuse_a_guessed_or_missing_value(tmp: Path) -> None:
    (tmp / "PROGRESS.md").write_text("# Progress\n", encoding="utf-8")
    for words in (("stage_end", "stage=implement", "tokens_reported=lots"), ("stage_end", "stage=implement"),
                  ("stage_start", "stage=deploy"), ("stage_end", "stage=review", "personas=x", "tokens_reported=1")):
        refused = metric(tmp, *words)
        assert refused.returncode == 1 and "log-metric:" in refused.stderr, (words, refused.stderr)
    assert "stage_" not in (tmp / "PROGRESS.md").read_text(encoding="utf-8"), "a refused line is not written"
    assert metric(tmp, "implement_start", "mode=inline").returncode == 0, "the free-form keys still work"


def test_crew_ls_cost_reads_the_same_lines(tmp: Path) -> None:
    owner = tmp / "tasks" / "abc"
    owner.mkdir(parents=True)
    (owner / "PROGRESS.md").write_text("# Progress\n", encoding="utf-8")
    metric(owner, "stage_end", "stage=implement", "workers=2", "tokens_reported=100")
    metric(owner, "stage_end", "stage=implement", "workers=3", "tokens_reported=410000")
    metric(owner, "stage_end", "stage=review", "personas=4", "tokens_reported=380000")
    (tmp / "tasks" / "empty").mkdir()
    listed = subprocess.run([sys.executable, str(LS_CLI), "--tasks-dir", str(tmp / "tasks"), "--cost"],
                            capture_output=True, text=True)
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.strip() == "abc: implement: 3 workers, 410k tokens; review: 4 personas, 380k tokens", \
        listed.stdout


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for test in tests:
        with tempfile.TemporaryDirectory() as directory:
            try:
                test(Path(directory))
                print(f"pass: {test.__name__}")
            except Exception as error:
                failed += 1
                print(f"FAIL: {test.__name__}: {type(error).__name__}: {error}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
