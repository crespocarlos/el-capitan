#!/usr/bin/env python3
"""Hermetic checks for task-context.py: resolution, subsetting, truncation, rendering."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / ".agent" / "tools" / "task-context.py"

SPEC = "# Spec: demo\n\n## Status\nAPPROVED\n" + ("body line\n" * 40)
PROGRESS = "".join(f"[2026-11-{day:02d} 10:00] TRANSITION: step {day}\n" for day in range(1, 29))
REVIEW = "# Review\n\n" + ("finding text here\n" * 60) + "\n### Files reviewed\n- `a.py`\n\nReviewed at: abcdef1\n"


def run(*arguments, task_dir=None, unset_cache=False):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("CREW_TASK_DIR", None) if unset_cache else None
    if task_dir:
        env["CREW_TASK_DIR"] = str(task_dir)
    return subprocess.run([sys.executable, str(TOOL), *arguments],
                          capture_output=True, text=True, env=env)


def make_task(store):
    task = store / "task"
    task.mkdir()
    (task / ".task-id").write_text(json.dumps({
        "uuid": "TEST", "repo_remote_url": "git@example.invalid:owner/demo.git",
        "branch": "demo", "slug": "demo-task", "created_at": "2026-11-01T00:00:00Z",
    }))
    (task / "SPEC.md").write_text(SPEC)
    (task / "PROGRESS.md").write_text(PROGRESS)
    (task / "REVIEW.md").write_text(REVIEW)
    return task


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    print(f"pass: {name}")


def main():
    with tempfile.TemporaryDirectory() as temporary:
        store = Path(temporary)
        task = make_task(store)

        # Invalid invocations exit 2 and name the problem.
        for arguments, label in (
            (("--max-chars", "-1"), "negative max-chars"),
            (("--max-chars", "0"), "zero max-chars"),
            (("--artifacts", "spec,nope"), "unknown artifact key"),
            (("--artifacts", " , "), "empty artifact selection"),
        ):
            result = run(*arguments, task_dir=task)
            check(f"rejects {label}", result.returncode == 2, result.stdout + result.stderr)

        # CREW_TASK_DIR is honored without invoking the resolver.
        result = run("--json", task_dir=task)
        check("honors CREW_TASK_DIR", result.returncode == 0, result.stderr)
        payload = json.loads(result.stdout)
        check("reports the cached task", payload["task"]["directory"] == str(task), payload["task"])
        check("reads status from SPEC", payload["task"]["status"] == "APPROVED", payload["task"])
        check("defaults to every artifact", sorted(payload["artifacts"]) == sorted(
            ["task_id", "spec", "progress", "report", "review", "deferred", "handoff"]))
        check("absent artifact is reported", payload["artifacts"]["handoff"]["state"] == "absent")

        # Explicit --task-dir wins over the cache and subsets both renderings identically.
        result = run("--task-dir", str(task), "--artifacts", " spec , review ", "--json")
        payload = json.loads(result.stdout)
        check("strips whitespace in --artifacts", sorted(payload["artifacts"]) == ["review", "spec"],
              sorted(payload["artifacts"]))
        markdown = run("--task-dir", str(task), "--artifacts", "spec,review").stdout
        check("markdown omits unrequested artifacts", "PROGRESS.md" not in markdown, markdown[:200])

        # Truncation direction: reports keep the tail (identity fields), specs keep the head.
        payload = json.loads(run("--task-dir", str(task), "--max-chars", "200", "--json").stdout)
        review = payload["artifacts"]["review"]
        check("review is truncated", review["truncated"] is True)
        check("review keeps its tail", "Reviewed at: abcdef1" in review["content"], review["content"])
        check("review records the edge", review["truncated_edge"] == "tail")
        spec = payload["artifacts"]["spec"]
        check("spec keeps its head", spec["content"].startswith("# Spec: demo"))
        progress = payload["artifacts"]["progress"]
        check("progress keeps its newest events", "step 28" in progress["content"], progress["content"])
        check("bytes is the file size", spec["bytes"] == len(SPEC.encode("utf-8")))

        markdown = run("--task-dir", str(task), "--max-chars", "200", "--artifacts", "review").stdout
        check("markdown flags truncation in the header", "TRUNCATED" in markdown, markdown[:300])

        # An explicit branch describes another context, so the cached task is not reused.
        result = run("--json", "--remote", "https://example.invalid/none.git", "--branch", "none",
                     task_dir=task)
        check("branch override resolves fresh", json.loads(result.stdout)["task"]["found"] is False)

        # A non-task directory is an invocation error, not an empty result.
        check("rejects a non-task directory", run("--task-dir", str(store)).returncode == 2)

        # No task anywhere: exit 0 with every requested artifact absent.
        result = run("--json", "--remote", "https://example.invalid/none.git", "--branch", "none",
                     unset_cache=True)
        check("no task exits 0", result.returncode == 0, result.stderr)
        payload = json.loads(result.stdout)
        check("no task reports found false", payload["task"]["found"] is False, payload["task"])
        check("no task reports every artifact absent",
              all(entry["state"] == "absent" for entry in payload["artifacts"].values()))

    print("all task-context checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
