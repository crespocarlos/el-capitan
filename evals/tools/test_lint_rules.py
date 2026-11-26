#!/usr/bin/env python3
"""crew-lint's rule registry and its repository Python rules, through the command.

The real tree reports nothing; a temp copy of `.agent/tools` with one seeded violation per case
reports its rule; every rule a run reports is registered, and `--list-rules` prints them all.
Generic Python style is Ruff's (`ruff.toml`) and is not retested here.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".agent" / "tools"
LINT = TOOLS / "maintenance" / "crew-lint.py"
FAILED: list[str] = []

# (case, rule, file under .agent/tools, text appended to it: a new file starts empty)
SEEDED = (
    ("git-argv", "direct-git", "task/task_seeded.py", "ARGV = [\"git\", \"status\"]\n"),
    ("long-module", "module-size", "task/task_seeded.py", "X = 1\n" * 401),
    ("second-atomic-write", "single-owner", "task/task_seeded.py", "def atomic_write() -> None:\n    pass\n"),
    ("systemexit-message", "no-systemexit-str", "task/task_seeded.py", "raise SystemExit(f'bad: {1}')\n"),
    ("task-imports-review", "package-direction", "task/task_seeded.py", "import review_pr_reads\n"),
    ("lib-imports-task", "package-direction", "lib/seeded.py",
     "def later() -> None:\n    from task_progress import read_text\n"),
    ("memory-imports-maintenance", "package-direction", "memory/memory_seeded.py", "from lint_files import rel\n"),
    ("second-read-json", "single-owner", "review/review_seeded.py", "def read_json() -> None:\n    pass\n"),
    ("progress-append", "single-owner", "task/task_seeded.py",
     "from pathlib import Path\n\nPath('t', 'PROGRESS.md').open('a').write('x')\n"),
    ("slug-regex", "single-owner", "task/task_seeded.py",
     "import re\n\nSLUG = re.compile(r'[:/]([^/:]+)/([^/]+?)(?:\\.git)?$')\n"),
    ("removed-verify-form", "removed-command-form", "task/task_seeded.py",
     "USAGE = 'crew-progress.py verify --repo .'\n"),
    ("removed-mark-flag", "removed-command-form", "TOOLS.md", "\nRun `crew-ls.py --mark-done \"$TASK_DIR\"`.\n"),
    ("removed-wrapped-form", "removed-command-form", "TOOLS.md", "\napplied by `crew-ls.py --reconcile\n--apply`.\n"),
    ("removed-form-in-eval-task", "removed-command-form", "../../evals/tasks.json",
     '{"d": "run `crew-ls.py --mark-done x`"}\n'),
    ("removed-form-in-prompt-case", "removed-command-form", "../../evals/prompts/cases/seeded.json",
     '{"artifact": "crew-progress.py verify --repo ."}\n'),
    ("long-docstring", "docstring-length", "task/task_seeded.py", '"""One.\n\n2\n3\n4\n5\n6\n7\n"""\n'),
    ("narrated-comment", "no-incident-narration", "task/task_seeded.py", "X = 1  # this used to crash\n"),
    ("measured-docstring", "no-incident-narration", "review/review_seeded.py",
     '"""A reader: measured over 9 runs, 3 of 9 failed."""\n'),
    ("bootstrap-drift", "bootstrap-identical", "task/task_bootstrap.py", "EXTRA = 1\n"),
    ("sibling-run", "no-sibling-subprocess", "task/task_seeded.py",
     "import subprocess\n\nsubprocess.run(['python3', 'crew-ls.py'])\n"),
    ("sibling-path", "no-sibling-subprocess", "review/review_seeded.py",
     "import subprocess\nfrom pathlib import Path\n\nTOOL = Path(__file__).with_name('crew-pr-actions.py')\n"
     "subprocess.run([TOOL, 'pr'])\n"),
)


def check(name: str, condition: bool, detail: object = "") -> None:
    print(f"{'pass' if condition else 'FAIL'}: {name}{'' if condition else f': {detail}'}")
    if not condition:
        FAILED.append(name)


def run(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(LINT), *arguments], capture_output=True, text=True,
                          timeout=120)


def registered() -> set[str]:
    listing = run("--list-rules")
    check("--list-rules exits 0", listing.returncode == 0, listing.stderr)
    return {line.split()[0] for line in listing.stdout.splitlines() if line.strip()}


def seeded_findings(base: Path, case: str, target: str, text: str) -> list[dict]:
    """crew-lint --json over a copy of the tool tree with one seeded change."""
    root = base / case
    shutil.copytree(TOOLS, root / ".agent" / "tools", ignore=shutil.ignore_patterns("__pycache__"))
    (root / "rules").mkdir()
    path = root / ".agent" / "tools" / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((path.read_text() if path.exists() else "") + text)
    result = run("--root", str(root), "--json")
    check(f"seeded {case} exits 1", result.returncode == 1, result.stderr[-400:])
    return json.loads(result.stdout or "[]")


def ruff_owns_sys_path() -> None:
    """`sys.path` is Ruff's TID251 ban; only the five bootstraps and tests under evals/ are exempt, by name."""
    text = (ROOT / "ruff.toml").read_text(encoding="utf-8")
    select = next(line for line in text.splitlines() if line.startswith("select = "))
    check("ruff.toml bans sys.path (TID251)", '"sys.path".msg' in text and '"TID251"' in select, select)
    exempt = [line.split('"')[1] for line in text.splitlines()
              if line.startswith('"') and '"TID251"' in line]
    allowed = [path for path in exempt if path.endswith("_bootstrap.py") or path.startswith("evals/")]
    check("TID251 is waived only for the bootstraps and evals tests, by name",
          exempt == allowed and "*" not in "".join(exempt), exempt)
    check("all five bootstraps are waived", sum(path.endswith("_bootstrap.py") for path in exempt) == 5, exempt)


def main() -> int:
    ruff_owns_sys_path()
    rules = registered()
    check("small-module-reason and no-sys-path (now Ruff TID251) are gone from the registry",
          not {"small-module-reason", "no-sys-path"} & rules)
    for rule in sorted({rule for _, rule, _, _ in SEEDED}):
        check(f"{rule} is listed", rule in rules)
    clean = run()
    check("the real tree passes", clean.returncode == 0, clean.stdout[-800:])
    with tempfile.TemporaryDirectory() as temp:
        for case, rule, target, text in SEEDED:
            found = seeded_findings(Path(temp), case, target, text)
            check(f"seeded {case} reports {rule}", any(item["rule"] == rule for item in found),
                  [item["rule"] for item in found])
            unknown = {item["rule"] for item in found} - rules
            check(f"seeded {case}: every reported rule is registered", not unknown, unknown)
    print("lint-rules: fail" if FAILED else "lint-rules: pass")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
