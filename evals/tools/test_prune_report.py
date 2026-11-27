#!/usr/bin/env python3
"""Checks for the prune report: a command with no reference anywhere is the only automatic verdict.

The command surface grows faster than it is exercised, and nothing noticed when four tools lost
their last caller. These cases build a throwaway repository with one called command, one named only
by a test, and one named nowhere, and assert the report separates them — because a report that
counts documentation as a caller answers "everything is called" and measures nothing.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRUNE = ROOT / ".agent" / "tools" / "maintenance" / "crew-prune.py"

FAILED: list[str] = []
CATALOG = {
    "schema_version": 1,
    "tools": [
        {"name": "crew-called.py", "dir": "task", "kind": "command", "category": "task",
         "owner": "repository", "help": "argparse", "smoke": "--help"},
        {"name": "crew-tested.py", "dir": "task", "kind": "command", "category": "task",
         "owner": "repository", "help": "argparse", "smoke": "--help"},
        {"name": "crew-orphan.py", "dir": "task", "kind": "command", "category": "task",
         "owner": "repository", "help": "argparse", "smoke": "--help"},
    ],
    "scripts": [],
    "modules": [{"name": "helper_module.py", "dir": "task", "kind": "module", "category": "task",
                 "owner": "repository", "help": "imported", "smoke": "imported"}],
    "assets": [],
}


def check(name: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"pass: {name}")
        return
    FAILED.append(name)
    print(f"FAIL: {name}{': ' + str(detail) if detail else ''}")


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture(base: Path) -> Path:
    """A tiny repository: one command in a prompt, one in a test, one in nothing."""
    root = base / "repo"
    write(root, ".agent/tools/tools.json", json.dumps(CATALOG, indent=2))
    for name in ("crew-called.py", "crew-tested.py", "crew-orphan.py"):
        write(root, f".agent/tools/task/{name}", f"#!/usr/bin/env python3\n\"\"\"{name} does a thing.\"\"\"\n")
    write(root, ".agent/tools/task/helper_module.py", '"""Imported, never invoked."""\n')
    write(root, "rules/crew-router.mdc", "# Router\n\nThe pipeline runs `~/.agent/bin/crew-called.py`.\n")
    write(root, "install.sh", "#!/usr/bin/env bash\nln -sf a b\n")
    write(root, ".agent/tools/AGENTS.md", "# Tools\n")
    write(root, ".agent/tools/TOOLS.md",
          "# Tools\n\n`crew-called.py`, `crew-tested.py`, and `crew-orphan.py` are all documented.\n")
    write(root, "evals/tools/test_something.py",
          "#!/usr/bin/env python3\n\"\"\"A test.\"\"\"\nTOOL = \"crew-tested.py\"\n")
    return root


def report(root: Path, *arguments: str) -> tuple[int, list[dict], str]:
    result = subprocess.run([sys.executable, str(PRUNE), "--root", str(root), "--json", *arguments],
                            capture_output=True, text=True)
    try:
        rows = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        rows = []
    return result.returncode, rows, result.stdout + result.stderr


def verdicts(rows: list[dict]) -> dict[str, str]:
    return {row["name"]: row["verdict"] for row in rows}


def fixture_cases(base: Path) -> None:
    """The fixture names exactly one uncalled command, and the exit code says so."""
    root = fixture(base)
    code, rows, output = report(root)
    verdict = verdicts(rows)
    check("the fixture's uncalled command is the only uncalled one",
          [name for name, state in verdict.items() if state == "uncalled"] == ["crew-orphan.py"],
          verdict)
    check("a command a prompt names is called", verdict.get("crew-called.py") == "called", verdict)
    check("a command only a test names is test-only",
          verdict.get("crew-tested.py") == "test-only", verdict)
    check("an uncalled command fails the report", code == 1, code)
    check("the documented catalog page is not a caller", verdict.get("crew-orphan.py") != "called",
          verdict)
    check("a module is not reported as a command",
          "helper_module.py" not in verdict, sorted(verdict))


def table_cases(base: Path) -> None:
    """The human report names the same command and prints a table with one row per command."""
    root = fixture(base)
    result = subprocess.run([sys.executable, str(PRUNE), "--root", str(root)],
                            capture_output=True, text=True)
    check("the table names the uncalled command", "crew-orphan.py" in result.stdout, result.stdout)
    check("the table says how many are uncalled", "1 uncalled" in result.stdout, result.stdout)
    body = [line for line in result.stdout.splitlines() if line.startswith("crew-")]
    check("the table has one row per command", len(body) == 3, body)
    check("the table's exit code reports the finding", result.returncode == 1, result.returncode)


def install_cases(base: Path) -> None:
    """A command the installer links is a caller, because install.sh names it."""
    root = fixture(base)
    write(root, "install.sh", "#!/usr/bin/env bash\nln -sf crew-orphan.py b\n")
    code, rows, _ = report(root)
    verdict = verdicts(rows)
    check("an installer reference counts as a caller", verdict.get("crew-orphan.py") == "called",
          verdict)
    check("nothing is uncalled, so the report exits 0", code == 0, code)


def description_cases(base: Path) -> None:
    """A docstring, a comment or a tool-tree `.md` doc describes a command; it does not call it."""
    root = fixture(base)
    write(root, ".agent/tools/task/helper_module.py",
          '"""Wraps crew-orphan.py."""\n# crew-orphan.py is described here\nVALUE = 1\n')
    write(root, ".agent/tools/AGENTS.md", "# Tools\n\nRun `crew-orphan.py` to see.\n")
    code, rows, _ = report(root)
    check("a docstring, a comment and a tool-tree doc are not callers",
          verdicts(rows).get("crew-orphan.py") == "uncalled", verdicts(rows))
    check("the report still fails for an uncalled command", code == 1, code)
    write(root, ".agent/tools/task/helper_module.py", 'COMMAND = "crew-orphan.py"\n')
    check("a string in code is a caller", verdicts(report(root)[1]).get("crew-orphan.py") == "called")


def unreadable_catalog_cases(base: Path) -> None:
    """A missing catalog is an invocation failure, not "everything is called"."""
    root = base / "empty"
    root.mkdir(parents=True, exist_ok=True)
    code, _, output = report(root)
    check("an unreadable catalog exits 2", code == 2, (code, output))
    check("an unreadable catalog says why", "cannot read the catalog" in output, output)


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="crew-prune-"))
    try:
        fixture_cases(base / "one")
        table_cases(base / "two")
        install_cases(base / "three")
        description_cases(base / "four")
        unreadable_catalog_cases(base / "five")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("all prune-report checks passed" if not FAILED else f"prune: {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
