#!/usr/bin/env python3
"""Checks for the prune report: a command with no reference anywhere is the only automatic verdict.

These cases build a throwaway repository with one called command, one named only by a test, and one
named nowhere, and assert the report separates them, because a report that counts documentation as a
caller answers "everything is called" and measures nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

from cli_runner import run as cli

ROOT = Path(__file__).resolve().parents[2]
PRUNE = ROOT / ".agent" / "tools" / "maintenance" / "crew-prune.py"

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


def report(root: Path, *arguments: str) -> tuple[int, dict[str, str], str]:
    """Exit code, the verdict per command name, and the output."""
    result = cli(PRUNE, "--root", str(root), "--json", *arguments)
    try:
        rows = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        rows = []
    return result.returncode, {row["name"]: row["verdict"] for row in rows}, result.stdout + result.stderr


def test_the_fixture_names_exactly_one_uncalled_command(tmp: Path) -> None:
    """A documented catalog page is not a caller, and a module is not a command."""
    code, verdict, _ = report(fixture(tmp))
    assert verdict == {"crew-called.py": "called", "crew-tested.py": "test-only", "crew-orphan.py": "uncalled"}, verdict
    assert code == 1


def test_the_table_has_one_row_per_command(tmp: Path) -> None:
    result = cli(PRUNE, "--root", str(fixture(tmp)))
    body = [line for line in result.stdout.splitlines() if line.startswith("crew-")]
    assert "crew-orphan.py" in result.stdout and "1 uncalled" in result.stdout, result.stdout
    assert len(body) == 3 and result.returncode == 1, (body, result.returncode)


def test_an_installer_reference_is_a_caller(tmp: Path) -> None:
    root = fixture(tmp)
    write(root, "install.sh", "#!/usr/bin/env bash\nln -sf crew-orphan.py b\n")
    code, verdict, _ = report(root)
    assert verdict.get("crew-orphan.py") == "called" and code == 0, (verdict, code)


def test_a_description_is_not_a_caller_and_a_string_in_code_is(tmp: Path) -> None:
    """A docstring, a comment or a tool-tree `.md` doc describes a command; it does not call it."""
    root = fixture(tmp)
    write(root, ".agent/tools/task/helper_module.py",
          '"""Wraps crew-orphan.py."""\n# crew-orphan.py is described here\nVALUE = 1\n')
    write(root, ".agent/tools/AGENTS.md", "# Tools\n\nRun `crew-orphan.py` to see.\n")
    code, verdict, _ = report(root)
    assert verdict.get("crew-orphan.py") == "uncalled" and code == 1, (verdict, code)
    write(root, ".agent/tools/task/helper_module.py", 'COMMAND = "crew-orphan.py"\n')
    assert report(root)[1].get("crew-orphan.py") == "called"


def test_an_unreadable_catalog_exits_2(tmp: Path) -> None:
    code, _, output = report(tmp)
    assert code == 2 and "cannot read the catalog" in output, (code, output)
