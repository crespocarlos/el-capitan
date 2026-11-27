#!/usr/bin/env python3
"""The installed command surface: install links, `--help`, machine-readable output, bounds, exit codes.

- `install.sh` links the catalog's commands and nothing else, and refuses a basename that two
  directories both provide (a second `ln -sf` would silently replace the first);
- every command's `--help` succeeds and fits one screen (40 lines), and the subcommand helps show what
  they own; one in-process loop asks every Python entry point, so no interpreter starts per command;
- every command the catalog marks machine-readable prints valid JSON with nothing human before it;
- every command that prints a collection advertises its bound and prints a marker naming the cut;
- every non-standard exit code is a named `EXIT_*` constant with a row in `.agent/tools/AGENTS.md`.
Catalog kinds and command names are `crew-lint` rules (`catalog-kind-*`, `command-name`).
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cli_runner import run as cli

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".agent" / "tools"
INSTALL = ROOT / "install.sh"
SOURCE_ONLY = {"task-env.sh", "crew-diff.sh"}
HELP_LINE_CEILING = 40
TOOLS_DOC = (TOOLS / "TOOLS.md").read_text()
FAILED: list[str] = []
# (case, module, parser function, text the --help must show, text it must not)
HELP_TEXTS = (
    ("crew-task.py worktree --help lists every action, check included", "task_worktrees", "pref_main", ("pref", "record", "check <TREE>"), ()),
    ("crew-verify.py report-check --help describes the report check, not the task listing", "task_verify_report", "main", ("builder",),
     ("Rendering task state",)),
)
SAMPLE_DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,3 @@\n one\n-two\n+two\n+three\n"
EXIT_ROW = re.compile(r"^\| `(crew-[a-z0-9-]+\.py[^`]*)` \| `([3-9])` \| [^|]+ \| `([a-z0-9_/-]+\.py)` \|$")


def check(name: str, condition: bool, detail: object = "") -> None:
    print(("pass: " if condition else "FAIL: ") + name + ("" if condition else f": {detail}"))
    if not condition:
        FAILED.append(name)


def catalog() -> list[dict]:
    data = json.loads((TOOLS / "tools.json").read_text())
    return [entry for section in ("tools", "scripts", "modules", "assets") for entry in data.get(section, [])]


def commands() -> list[dict]:
    return [entry for entry in catalog() if entry.get("kind") == "command" and entry["name"] not in SOURCE_ONLY]


def command(entry: dict, *arguments: str, env: dict | None = None, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    """A Python command runs in this process; a shell one in bash."""
    path = TOOLS / entry["dir"] / entry["name"]
    if path.suffix == ".py":
        return cli(path, *arguments, env=env, cwd=cwd)
    return subprocess.run(["bash", str(path), *arguments], capture_output=True, text=True, env={**os.environ, **(env or {})}, cwd=cwd, timeout=120)


def scratch_repo(path: Path) -> Path:
    """A one-commit repository with no remote, so `crew-worktree.py main` resolves without the network."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    return path


def dry_run(home: str, script: Path = INSTALL) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key not in ("CREW_MEMORY_DIR", "CREW_JOURNAL_DIR", "CREW_TASK_DIR")}
    return subprocess.run(["bash", str(script), "--dry-run"], capture_output=True, text=True, env={**env, "HOME": home})


def install_links(tmp: Path) -> None:
    """The dry-run link set is exactly the catalog's commands, each once; a duplicated basename is refused."""
    result = dry_run(str(tmp / "home"))
    linked = [Path(target).name for target in re.findall(r"ln -sf (\S+) ", result.stdout) if "/.agent/tools/" in target]
    names = {entry["name"] for entry in catalog() if entry.get("kind") == "command"}
    check("install --dry-run links every command, nothing else, each once",
          result.returncode == 0 and set(linked) == names and len(linked) == len(set(linked)),
          (result.stderr[-300:], sorted(set(linked) ^ names)))
    source = tmp / "dup-src"
    for package in ("task", "review"):
        (source / ".agent" / "tools" / package).mkdir(parents=True)
        shutil.copy(TOOLS / "task" / "crew-progress.py", source / ".agent" / "tools" / package / "crew-progress.py")
    shutil.copy(INSTALL, source / "install.sh")
    for name in ("rules", ".claude", ".cursor"):
        (source / name).symlink_to(ROOT / name)
    refused = dry_run(str(tmp / "dup-home"), source / "install.sh")
    check("a basename in two tool directories is refused, naming both", refused.returncode != 0 and re.search(
        r"error: duplicate command crew-progress.py in .*tools/review/crew-progress.py and .*tools/task/crew-progress.py", refused.stderr), refused.stderr[-300:])


def help_text(module: str, function: str) -> str:
    import contextlib
    import importlib
    import io

    for path in (str(TOOLS / "task"), str(TOOLS)):
        if path not in sys.path:
            sys.path.insert(0, path)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.suppress(SystemExit):
        getattr(importlib.import_module(module), function)(["--help"])
    return buffer.getvalue()


def help_cases() -> dict[str, str]:
    """Every command's `--help` succeeds within the ceiling; returns the texts for the bound checks."""
    texts = {}
    for entry in commands():
        result = command(entry, "--help")
        texts[entry["name"]] = result.stdout + "".join(command(entry, *sub).stdout for sub in entry.get("flag_help", []))
        lines = result.stdout.count("\n") or 1
        check(f"{entry['name']}: --help succeeds in {lines} <= {HELP_LINE_CEILING} lines",
              result.returncode == 0 and lines <= HELP_LINE_CEILING, (result.returncode, lines, result.stderr[-300:]))
    for label, module, function, wanted, unwanted in HELP_TEXTS:
        text = help_text(module, function)
        check(label, all(w in text for w in wanted) and not any(u in text for u in unwanted), text)
    return texts


def is_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except json.JSONDecodeError:
        return False


def write_unit(store: Path, name: str) -> None:
    unit = store / "global" / f"user_demo-{name}.md"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(f"---\nid: user-demo-{name}\ntype: user\nscope: global\ntitle: demo-{name}\npaths: []\nkeywords: []\nstatus: active\n"
                    f"created: 2026-01-01\nmodified: 2026-01-01\nevidence: []\nuses: 0\nhelped: 0\nmisled: 0\n---\nA demo preference for {name}.\n",
                    encoding="utf-8")


def output_cases(tmp: Path, texts: dict[str, str]) -> None:
    """JSON on stdout for each machine-readable command; every bound advertised and marked when it cuts."""
    diff = tmp / "sample.diff"
    diff.write_text(SAMPLE_DIFF, encoding="utf-8")
    memory = {"CREW_MEMORY_DIR": str(tmp / "memory"), "CREW_TASK_DIR": None}
    by_name = {entry["name"]: entry for entry in commands()}
    repo = scratch_repo(tmp / "repo")
    initialized = command(by_name["crew-mem.py"], "init", env=memory)
    check("crew-mem.py init prepares a scratch store", initialized.returncode == 0, initialized.stderr[-300:])
    for entry in commands():
        name, mode = entry["name"], entry.get("output")
        for flag in entry.get("list_flags", []) if entry.get("bounded") else []:
            check(f"{name}: --help documents its bound {flag}", flag in texts[name])
        if mode not in {"json", "json-always", "json_static", "json-flag"}:
            continue
        check(f"{name}: documented as machine-readable in TOOLS.md", name in TOOLS_DOC)
        if mode == "json-flag":
            check(f"{name}: diagnose accepts --json", "--json" in command(entry, "diagnose", "--help").stdout)
        if mode in ("json", "json-always"):
            arguments = [item.replace("@tmpdir", str(tmp)).replace("@diff", str(diff)) for item in entry.get("json_smoke", [])]
            result = command(entry, *arguments, env=memory, cwd=repo if name == "crew-worktree.py" else ROOT)
            check(f"{name}: stdout is valid JSON with nothing human before it",
                  is_json(result.stdout) and not result.stdout.lstrip().startswith(("pass:", "FAIL", "usage:")),
                  f"exit {result.returncode}; stdout starts {result.stdout[:160]!r}")
    tasks = tmp / "tasks"
    for index in range(6):
        (tasks / f"task-{index}").mkdir(parents=True)
        (tasks / f"task-{index}" / "SPEC.md").write_text(f"# Task {index}\n\n## Status\nDRAFTING\n\n- [ ] a\n", encoding="utf-8")
    limited = command(by_name["crew-ls.py"], "--tasks-dir", str(tasks), "--limit", "2").stdout
    clipped = command(by_name["crew-ls.py"], "--tasks-dir", str(tasks), "--max-chars", "120").stdout
    check("crew-ls.py: --limit and --max-chars print a marker naming the bound",
          "[truncated:" in limited and "--limit" in limited and "[truncated:" in clipped, (limited, clipped))
    check("crew-ls.py: --json stays parseable when bounded", is_json(command(by_name["crew-ls.py"], "--tasks-dir", str(tasks), "--limit", "2", "--json").stdout))
    hunks = command(by_name["crew-review-hunks.py"], str(diff), "--out", str(tmp / "hunks2"), "--max-chars", "40").stdout
    check("crew-review-hunks.py: --max-chars marks a clipped JSON summary", is_json(hunks) and "truncated" in hunks, hunks)
    path = command(by_name["crew-worktree.py"], "main", "--json", "--max-chars", "5", cwd=repo).stdout
    check("crew-worktree.py: --max-chars marks a clipped path", "[truncated:" in path, path)
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feat", str(tmp / "feat")], check=True)
    held = command(by_name["crew-worktree.py"], "feat", "--json", cwd=repo).stdout
    check("crew-worktree.py: a branch another worktree holds resolves to that worktree",
          is_json(held) and Path(json.loads(held)["path"]).resolve() == (tmp / "feat").resolve(), held)
    for name in ("alpha", "beta", "gamma"):
        write_unit(tmp / "memory", name)
    listed = command(by_name["crew-mem.py"], "list", "--json", "--limit", "1", env=memory).stdout
    payload = json.loads(listed) if is_json(listed) else None
    check("crew-mem.py: --limit wraps a clipped list in an envelope naming the bound",
          isinstance(payload, dict) and payload.get("truncated") is True and payload.get("total") == 3 and "--limit" in payload.get("hint", ""), listed)


def exit_code_cases() -> None:
    """Every non-standard exit code is a named `EXIT_*` constant and has a row in the AGENTS.md table."""
    guide = (TOOLS / "AGENTS.md").read_text(encoding="utf-8")
    documented = {(found.group(3), int(found.group(2))) for found in map(EXIT_ROW.match, guide.splitlines()) if found}
    declared, bare = set(), []
    for path in sorted(TOOLS.rglob("*.py")):
        source = path.relative_to(TOOLS).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id.startswith("EXIT_") and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, int) and node.value.value >= 3):
                declared.add((source, node.value.value))
            if (isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, int)
                    and not isinstance(node.value.value, bool) and node.value.value >= 3):
                bare.append(f"{source}:{node.lineno} return {node.value.value}")
    check("the exit-code table lists the known non-standard codes", len(documented) >= 6, sorted(documented))
    check("no bare `return <3..9>`: a non-standard code is a named EXIT_* constant", not bare, bare)
    check("every EXIT_* constant is documented, and every documented code declared", declared == documented, sorted(declared ^ documented))


def main() -> int:
    exit_code_cases()
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        install_links(tmp)
        output_cases(tmp, help_cases())
    print(f"command surface: {len(FAILED)} failed" if FAILED else "command surface: pass")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
