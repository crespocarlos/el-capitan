#!/usr/bin/env python3
"""dispatch.py — parallel persona dispatch for crew degraded fallbacks.

Usage:
  dispatch.py --type reviewers     # crew-reviewer fallback
  dispatch.py --type critics       # crew-specwriter fallback
  dispatch.py --type perspectives  # crew-thinker fallback

Environment variables (common):
  REPO_ROOT           — git repo root (auto-detected if unset)
  CLAUDE_FAST_MODEL   — model name for fast personas (default: sonnet)

reviewers:
  TASK_DIR, REVIEW_MODE (self|pr|spec), DIFF_CONTENT

critics:
  TASK_DIR

perspectives:
  TASK_DIR, TOPIC, JOURNAL_CONTEXT_FULL, JOURNAL_CONTEXT_TOP5
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_claude() -> str:
    path = shutil.which("claude")
    if not path:
        print("dispatch: claude not found in PATH", file=sys.stderr)
        sys.exit(1)
    return path


def git_output(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def timeout_prefix() -> list[str]:
    for cmd in ("timeout", "gtimeout"):
        if shutil.which(cmd):
            return [cmd, "180"]
    return []


def run_persona(
    claude: str,
    timeout_cmd: list[str],
    prompt_path: Path,
    output_path: Path,
    stderr_path: Path,
    model_flag: list[str],
) -> int:
    cmd = [*timeout_cmd, claude, "-p", *model_flag]
    with open(prompt_path, "rb") as stdin_f, \
         open(output_path, "wb") as stdout_f, \
         open(stderr_path, "wb") as stderr_f:
        r = subprocess.run(cmd, stdin=stdin_f, stdout=stdout_f, stderr=stderr_f)
    return r.returncode


def read_persona(repo_root: Path, subdir: str, name: str) -> str:
    p = repo_root / ".cursor" / "agents" / f"{subdir}-{name}.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def dispatch_all(
    claude: str,
    timeout_cmd: list[str],
    run_dir: Path,
    names: list[str],
    fast_set: set[str],
    fast_model: str,
) -> tuple[list[str], list[str]]:
    """Dispatch all personas in parallel; return (successes, failures)."""
    futures: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        for name in names:
            model_flag = ["--model", fast_model] if name in fast_set else []
            f = pool.submit(
                run_persona, claude, timeout_cmd,
                run_dir / "prompts" / f"{name}.txt",
                run_dir / "output" / f"{name}.txt",
                run_dir / "output" / f"{name}.stderr",
                model_flag,
            )
            futures[name] = f

        successes, failures = [], []
        for name, future in futures.items():
            try:
                rc = future.result()
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{name} (exception: {exc})")
                continue
            out = run_dir / "output" / f"{name}.txt"
            if rc != 0:
                stderr_path = run_dir / "output" / f"{name}.stderr"
                stderr_snippet = ""
                if stderr_path.exists():
                    raw = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
                    stderr_snippet = f"\n  stderr: {raw[:500]}" if raw else ""
                failures.append(f"{name} (exit {rc}){stderr_snippet}")
            elif not out.exists() or out.stat().st_size == 0:
                failures.append(f"{name} (empty output)")
            else:
                successes.append(name)
    return successes, failures


def make_run_dir(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(dir=base, prefix="run-"))
    (run / "prompts").mkdir()
    (run / "output").mkdir()
    return run


def print_outputs(run_dir: Path, names: list[str]) -> None:
    for name in names:
        out = run_dir / "output" / f"{name}.txt"
        if out.exists() and out.stat().st_size > 0:
            print(f"=== {name} ===")
            print(out.read_text(encoding="utf-8"))
            print()


# ---------------------------------------------------------------------------
# Reviewers
# ---------------------------------------------------------------------------

def dispatch_reviewers(claude: str, timeout_cmd: list[str], repo_root: Path) -> int:
    task_dir = os.environ.get("TASK_DIR", "")
    review_mode = os.environ.get("REVIEW_MODE", "self")
    diff_content = os.environ.get("DIFF_CONTENT", "")
    fast_model = os.environ.get("CLAUDE_FAST_MODEL", "sonnet")

    repo = repo_root.name
    branch = git_output("branch", "--show-current")

    reviewers = ["code-quality", "adversarial", "fresh-eyes", "architecture", "product-flow"]
    fast_reviewers = {"code-quality", "product-flow"}

    if review_mode == "spec" and task_dir:
        dispatch_base = Path(task_dir) / "personas"
    else:
        dispatch_base = Path.home() / ".agent" / "reviews" / repo / branch / "personas"

    run_dir = make_run_dir(dispatch_base)

    # Resolve source material
    if diff_content:
        source = diff_content
    elif review_mode == "spec" and task_dir and (Path(task_dir) / "SPEC.md").exists():
        source = (Path(task_dir) / "SPEC.md").read_text(encoding="utf-8")
    else:
        r = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "main...HEAD"],
            capture_output=True, text=True,
        )
        if r.returncode != 0 or not r.stdout:
            r = subprocess.run(
                ["git", "-C", str(repo_root), "diff", "HEAD~1"],
                capture_output=True, text=True,
            )
        source = r.stdout or ""

    for reviewer in reviewers:
        persona = read_persona(repo_root, "reviewer", reviewer)
        prompt = (
            f"{persona}\n\n---\n\n"
            f"## Review context\n\nMode: {review_mode}\n\n"
            f"## Source material\n\n{source}\n\n---\n\n"
            "Produce your review now. Follow the output format in your persona definition.\n"
        )
        (run_dir / "prompts" / f"{reviewer}.txt").write_text(prompt, encoding="utf-8")

    successes, failures = dispatch_all(claude, timeout_cmd, run_dir, reviewers, fast_reviewers, fast_model)

    print_outputs(run_dir, reviewers)

    if failures:
        for f in failures:
            print(f"dispatch: reviewer failed: {f}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Critics
# ---------------------------------------------------------------------------

def dispatch_critics(claude: str, timeout_cmd: list[str], repo_root: Path) -> int:
    task_dir = os.environ.get("TASK_DIR", "")
    if not task_dir:
        print("dispatch: TASK_DIR required for --type critics", file=sys.stderr)
        return 1

    spec_path = Path(task_dir) / "SPEC.md"
    if not spec_path.exists():
        print(f"dispatch: SPEC.md not found at {spec_path}", file=sys.stderr)
        return 1

    spec = spec_path.read_text(encoding="utf-8")
    critics = ["scope", "adversarial"]

    run_dir = make_run_dir(Path(task_dir) / "personas")

    for critic in critics:
        persona = read_persona(repo_root, "specwriter", critic)
        prompt = (
            f"{persona}\n\n---\n\n"
            "## Critique context\n\n"
            "You are reviewing a draft SPEC.md before it is presented to the user.\n"
            "Find problems — do not suggest rewrites. The specwriter will apply fixes.\n\n"
            f"## Draft spec\n\n{spec}\n\n---\n\n"
            "Produce your critique now. Follow the output format in your persona definition.\n"
        )
        (run_dir / "prompts" / f"{critic}.txt").write_text(prompt, encoding="utf-8")

    successes, failures = dispatch_all(claude, timeout_cmd, run_dir, critics, set(), "")

    print_outputs(run_dir, critics)

    if failures:
        for f in failures:
            print(f"dispatch: critic failed: {f}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Perspectives
# ---------------------------------------------------------------------------

def dispatch_perspectives(claude: str, timeout_cmd: list[str], repo_root: Path) -> int:
    topic = os.environ.get("TOPIC", "")
    journal_full = os.environ.get("JOURNAL_CONTEXT_FULL", "")
    journal_top5 = os.environ.get("JOURNAL_CONTEXT_TOP5", "")
    fast_model = os.environ.get("CLAUDE_FAST_MODEL", "sonnet")

    if not topic:
        print("dispatch: TOPIC required for --type perspectives", file=sys.stderr)
        return 1

    repo = repo_root.name
    dispatch_base = Path.home() / ".agent" / "thinker" / repo / "personas"
    run_dir = make_run_dir(dispatch_base)

    profile_path = Path.home() / ".agent" / "PROFILE.md"
    try:
        profile = profile_path.read_text(encoding="utf-8")
    except OSError:
        profile = "(no profile)"

    def build_context(journal: str) -> str:
        return (
            f"**User profile:**\n{profile}\n\n"
            f"**Topic:**\n{topic}\n\n"
            f"**Journal context:**\n{journal}"
        )

    ctx_full = build_context(journal_full)
    ctx_top5 = build_context(journal_top5)

    perspectives = ["builder", "contrarian", "connector", "pragmatist"]
    fast_perspectives = {"pragmatist"}

    for perspective in perspectives:
        persona = read_persona(repo_root, "thinker", perspective)
        ctx = ctx_full if perspective == "connector" else ctx_top5
        prompt = (
            f"{persona}\n\n---\n\n"
            f"## Context\n\n{ctx}\n\n---\n\n"
            "Produce your output now. Follow the output format in your persona definition.\n"
        )
        (run_dir / "prompts" / f"{perspective}.txt").write_text(prompt, encoding="utf-8")

    successes, failures = dispatch_all(claude, timeout_cmd, run_dir, perspectives, fast_perspectives, fast_model)

    print_outputs(run_dir, perspectives)

    if failures:
        for f in failures:
            print(f"dispatch: perspective failed: {f}", file=sys.stderr)
        # Partial results are still useful — return 0 so the caller can use what succeeded.
        return 0
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Parallel persona dispatch for crew fallbacks.")
    parser.add_argument(
        "--type",
        required=True,
        choices=["reviewers", "critics", "perspectives"],
        help="Which persona set to dispatch",
    )
    parser.add_argument("--repo-root", default="", help="Git repo root (auto-detected if unset)")
    args = parser.parse_args()

    claude = find_claude()
    tc = timeout_prefix()

    repo_root_str = args.repo_root or git_output("rev-parse", "--show-toplevel")
    if not repo_root_str:
        print("dispatch: could not determine repo root", file=sys.stderr)
        sys.exit(1)
    repo_root = Path(repo_root_str)

    fn = {
        "reviewers": dispatch_reviewers,
        "critics": dispatch_critics,
        "perspectives": dispatch_perspectives,
    }[args.type]

    sys.exit(fn(claude, tc, repo_root))


if __name__ == "__main__":
    main()
