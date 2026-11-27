#!/usr/bin/env python3
"""What install.sh writes into the harness config, and `crew-doctor.py`'s check of it.

The block helpers are `.claude/install_blocks.py`, the module install.sh runs, so a change that breaks
idempotency, removal or user prose fails here first. The permission rules must not let an allow rule
shadow an ask rule (the outcome would depend on evaluation order), gate commands must prompt, and the
settings merge retires a broad rule the template narrowed while keeping the user's own. The doctor
runs against a fake HOME installed by install.sh, with a fake `gh` first on PATH.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest
from cli_runner import run as cli

PROJECT = Path(__file__).resolve().parents[2]
INSTALL = PROJECT / "install.sh"
SETTINGS = PROJECT / ".claude" / "settings.json"
MERGE = SETTINGS.parent / "merge_claude_settings.py"
BLOCKS = SETTINGS.parent / "install_blocks.py"
DOCTOR = PROJECT / ".agent" / "tools" / "maintenance" / "crew-doctor.py"
MEMORY = "<!-- el-capitan:memory -->\nMEMORY\n<!-- /el-capitan:memory -->"
IMPORTS = "<!-- el-capitan:imports -->\n@~/.cursor/rules/x.mdc\n<!-- /el-capitan:imports -->"
SEEDED = "# a\n\n<!-- el-capitan:memory -->\nstale\n<!-- /el-capitan:memory -->\n\n# b\n"


def check(name: str, condition: bool, detail: object = "") -> None:
    assert condition, f"{name}: {detail}"


def load_blocks() -> ModuleType:
    spec = importlib.util.spec_from_file_location("install_blocks", BLOCKS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_managed_blocks() -> None:
    blocks = load_blocks()
    upsert, remove = blocks.upsert, blocks.remove
    once = upsert("# notes\n", "memory", MEMORY)
    check("a block is appended to a file without one, keeping its text",
          "<!-- el-capitan:memory -->" in once and "# notes" in once)
    first = upsert(SEEDED, "memory", MEMORY)
    again = upsert(first, "memory", MEMORY)
    check("upsert replaces a stale block, keeps the text around it, is idempotent, and grows no blank lines",
          first == again == upsert(again, "memory", MEMORY) and "stale" not in first and "# a" in first
          and "# b" in first and not first.endswith("\n\n\n"), repr(first))
    both = upsert(upsert(SEEDED, "memory", MEMORY), "imports", IMPORTS)
    check("two blocks coexist and the two-block document is idempotent",
          "<!-- el-capitan:memory -->" in both and "@~/.cursor/rules/x.mdc" in both
          and upsert(upsert(both, "memory", MEMORY), "imports", IMPORTS) == both)
    removed = remove(remove(both, "memory"), "imports")
    check("removing both blocks gives back the text around them", removed == "# a\n\n# b", repr(removed))
    generated = blocks.global_rule_imports(PROJECT)
    expected: list[str] = []
    for target in re.findall(r"@(\S+\.mdc)", (PROJECT / ".claude/CLAUDE.md").read_text()):
        expected += [] if target in expected else [target]
    check("the generated imports block is fenced and imports exactly the project file's rules",
          re.findall(r"^@(\S+)$", generated, re.M) == expected and generated.startswith("<!-- el-capitan:imports -->")
          and generated.rstrip().endswith("<!-- /el-capitan:imports -->"), generated)


def command_of(rule: str) -> str | None:
    """The command a `Bash(<command> *)` rule names (it may contain spaces), or None for a non-Bash rule."""
    if not rule.startswith("Bash(") or not rule.endswith(")"):
        return None
    body = rule[len("Bash("):-1]
    return body[:-2] if body.endswith(" *") else body.rstrip(":*")


def test_permission_rules() -> None:
    permissions = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]
    allow_rules, ask_rules = permissions.get("allow", []), permissions.get("ask", [])
    allow = [c for c in map(command_of, allow_rules) if c]
    ask = [c for c in map(command_of, ask_rules) if c]
    check("the config has an allow list, and no ask rule uses the literal-colon form",
          bool(allow) and not any(":" in c.split(" ")[0] for c in ask), ask_rules)
    shadowed = [(a, s) for s in ask for a in allow if a.startswith(s) or s.startswith(a)]
    check("no allow rule shadows an ask rule", not shadowed, shadowed)
    check("an ask rule on a task directory targets a file, not its whole tree",
          all(not r.endswith("/**") for r in ask_rules if ".agent/tasks" in r), ask_rules)
    task = "~/.agent/bin/crew-task.py"
    gates = (f"{task} mark-approved /tmp/t", f"{task} mark-done /tmp/t", f"{task} mark-done /tmp/t --force")
    covered = [c for c in allow for command in gates if command == c or command.startswith(c + " ")]
    check("no allow rule covers Gate 1 or Gate 2, so each prompts", not covered, covered)
    routine = ("mark-implementing", "reconcile", "normalize-status", "lock", "blocked", "worktree")
    check("crew-task.py's routine subcommands and crew-review-findings.py are allowed one by one, not bin/*",
          all(f"{task} {name}" in allow for name in routine) and "~/.agent/bin/crew-review-findings.py" in allow
          and "~/.agent/bin/*" not in allow, [c for c in allow if "agent/bin" in c])
    check("hook fixtures are allowed without elevation", any("fixtures" in c for c in allow), allow)
    broad = {"Bash(~/.agent/bin/*)", "Bash(python3 *)", "Bash(node *)", "Bash(npx *)", "Bash(chmod *)"}
    broad &= set(allow_rules)
    prefixes = ("Bash(R=", "Bash(V=", "Bash(T=", "Bash(P=", "Bash(OUT=", "Bash(REVIEW_ROOT=")
    hidden = [r for r in allow_rules if r.startswith(prefixes) or (command_of(r) or "").endswith("=*")]
    check("no allow rule skips the command check or hides it behind an assignment",
          not broad and not hidden, (broad, hidden))


def test_settings_merge(tmp: Path) -> None:
    """The installer retires a broad rule when the template narrows it, and keeps the user's own rules."""
    user = {"permissions": {"allow": ["Bash(git *)", "Bash(my-own *)"],
                            "ask": ["Edit(~/.agent/tasks/**)", "Write(~/.agent/tasks/**)", "Edit(~/.claude/**)"]},
            "hooks": {}}
    dest = tmp / "dest.json"
    dest.write_text(json.dumps(user), encoding="utf-8")
    result = subprocess.run([sys.executable, str(MERGE), str(SETTINGS), str(dest)], capture_output=True, text=True)
    merged = json.loads(dest.read_text(encoding="utf-8"))["permissions"]
    check("the merge retires the broad task rule for the narrow one and keeps unrelated user rules",
          result.returncode == 0 and "Edit(~/.agent/tasks/**)" not in merged["ask"]
          and "Edit(~/.agent/tasks/*/SPEC.md)" in merged["ask"] and "Edit(~/.claude/**)" in merged["ask"]
          and "Bash(my-own *)" in merged["allow"], (result.stderr[-200:], merged))


@pytest.mark.parametrize("case, before, flag, after", [
    ("the key is written only with --auto-memory-off", {}, True, False),
    ("without the flag nothing is written", {}, False, None),
    ("a user's own true is kept", {"autoMemoryEnabled": True}, True, True),
    ("a user's own false is kept", {"autoMemoryEnabled": False}, True, False),
])
def test_settings_merge_auto_memory(tmp: Path, case: str, before: dict, flag: bool, after: object) -> None:
    """The merge writes `autoMemoryEnabled: false` only on request and never over a user's value; the unmerge of
    the install's record takes back only the false it added."""
    home, dest = tmp / "home", tmp / "home" / "cfg" / "settings.json"
    dest.parent.mkdir(parents=True)
    dest.write_text(json.dumps(before), encoding="utf-8")
    flags = ["--auto-memory-off"] if flag else []
    merged = subprocess.run([sys.executable, str(MERGE), str(SETTINGS), str(dest), "--manifest", str(home), *flags],
                            capture_output=True, text=True)
    value = json.loads(dest.read_text(encoding="utf-8")).get("autoMemoryEnabled")
    unmerge = ("import json, sys, merge_claude_settings as m; d = json.load(open(sys.argv[1])); "
               "r = next(v for k, v in json.load(open(sys.argv[2])).items() if k.startswith('claude_settings')); "
               "print(json.dumps(m.unmerge(d, r, json.load(open(sys.argv[3])), print).get('autoMemoryEnabled')))")
    undone = subprocess.run([sys.executable, "-c", unmerge, str(dest), str(home / ".agent/install-manifest.json"),
                             str(SETTINGS)], capture_output=True, text=True, cwd=MERGE.parent)
    check(f"{case}: merged as expected, and uninstall leaves the user's value",
          (merged.returncode, value, undone.returncode) == (0, after, 0)
          and json.loads(undone.stdout.splitlines()[-1]) == before.get("autoMemoryEnabled"),
          (merged.stderr[-300:], value, undone.stdout, undone.stderr[-300:]))


@pytest.fixture(scope="module")
def installed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One HOME install.sh installed into, with a second config dir `~/.claude-work`; each doctor case copies it."""
    home = tmp_path_factory.mktemp("installed") / "home"
    home.mkdir()
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("CREW_")}, "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude-work")}
    done = subprocess.run(["bash", str(INSTALL)], capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr[-400:]
    return home


def copy_install(installed: Path, home: Path) -> None:
    """A copy of the install whose manifest and links name the copy's directories, not the original's."""
    shutil.copytree(installed, home, symlinks=True)
    links = [Path(top) / name for top, dirs, files in os.walk(home) for name in dirs + files
             if (Path(top) / name).is_symlink()]
    for link in links:
        target = os.readlink(link)
        if target.startswith(str(installed) + os.sep):
            link.unlink()
            link.symlink_to(str(home) + target[len(str(installed)):])
    manifest = home / ".agent" / "install-manifest.json"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(str(installed), str(home)), encoding="utf-8")


def doctor(home: Path) -> tuple[int, list[tuple[str, str]]]:
    """The exit code and the (area, text) of each FAIL line; tools and gh are left out (they depend on the machine)."""
    done = cli(DOCTOR, "--offline", env={"HOME": str(home), "CREW_MEMORY_DIR": None})
    fails = [tuple(line.split(None, 2)[1:]) for line in done.stdout.splitlines() if line.split()[:1] == ["FAIL"]]
    return done.returncode, [(area, text) for area, text in fails if area not in ("tools", "gh")]


def edit_json(path: Path, change: Callable[[dict], None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def unmatch(data: dict) -> None:
    for entry in data["hooks"]["PreToolUse"]:
        entry["matcher"] = "NoSuchTool"


def drop_guard(data: dict) -> None:
    shell = data["hooks"]["beforeShellExecution"]
    data["hooks"]["beforeShellExecution"] = [e for e in shell if "credentials" not in e["command"]]


def drop_claude_guard(data: dict) -> None:
    for entry in data["hooks"]["PreToolUse"]:
        entry["hooks"] = [hook for hook in entry["hooks"] if "credentials" not in hook["command"]]


def tilde_hook(home: Path) -> None:
    edit_json(home / ".claude/settings.json", lambda data: data["hooks"]["Stop"].append(
        {"hooks": [{"type": "command", "command": "bash ~/.claude/hooks/tilde-gone.sh"}]}))


def absolute_hook(home: Path) -> None:
    edit_json(home / ".cursor/hooks.json", lambda data: data["hooks"]["beforeShellExecution"].append(
        {"command": f'bash "{home}/.claude/hooks/absolute-gone.sh"', "failClosed": True}))


def over_limit(home: Path) -> None:
    (home / ".agent" / "config.json").write_text(json.dumps({"doctor": {"tasks_mb": 0}}), encoding="utf-8")
    (home / ".agent" / "tasks" / "t").mkdir(parents=True)
    (home / ".agent" / "tasks" / "t" / "SPEC.md").write_text("x" * 2000, encoding="utf-8")


def telemetry(home: Path) -> None:
    (home / ".agent" / "telemetry").mkdir()
    (home / ".agent" / "telemetry" / "raw.jsonl").write_text('{"command": "x"}\n', encoding="utf-8")


STALE_BLOCK = "<!-- el-capitan:memory -->\nx\n<!-- /el-capitan:memory -->\n"
BAD_CONFIG = '{"gc": {"artifact_days": 1}}'


@pytest.mark.parametrize("case, damage, area, text", [
    ("fresh install", lambda home: None, None, None),
    ("broken link", lambda home: (home / ".cursor/rules/gone.mdc").symlink_to(PROJECT / "rules/gone.mdc"),
     "links", "gone.mdc"),
    ("edited block", lambda home: (home / ".claude/CLAUDE.md").write_text(STALE_BLOCK),
     "blocks", "CLAUDE.md memory block stale"),
    ("missing script", lambda home: (home / ".claude/hooks/guard").unlink(),
     "hooks", "scripts are missing: ~/.claude/hooks/guard/"),
    ("missing script, ~/ form", tilde_hook,
     "hooks", "Claude Code (~/.claude): registered hook scripts are missing: ~/.claude/hooks/tilde-gone.sh"),
    ("missing hook in the second config dir",
     lambda home: edit_json(home / ".claude-work/settings.json", drop_claude_guard),
     "hooks", "Claude Code (~/.claude-work): "),
    ("second config dir without agents", lambda home: (home / ".claude-work/agents").unlink(),
     "links", "~/.claude-work: not linked to ~/.cursor: agents"),
    ("missing script, absolute form", absolute_hook,
     "hooks", "Cursor: registered hook scripts are missing: ~/.claude/hooks/absolute-gone.sh"),
    ("wrong matcher", lambda home: edit_json(home / ".claude/settings.json", unmatch),
     "hooks", "missing or different PreToolUse Bash"),
    ("missing registration", lambda home: edit_json(home / ".cursor/hooks.json", drop_guard),
     "hooks", "guard/credentials.sh"),
    ("over-limit state", over_limit, "state", "tasks 0.0 MB (limit 0 MB); crew gc"),
    ("telemetry", telemetry, "state", "crew-task.py gc --only telemetry --apply"),
    ("bad config", lambda home: (home / ".agent/config.json").write_text(BAD_CONFIG), "config", "artifact_days"),
])
def test_doctor(installed: Path, tmp: Path, case: str, damage: Callable[[Path], object],
                area: str | None, text: str | None) -> None:
    """A fresh install is healthy; each damage is one FAIL line naming it, the other checks still run, exit 1."""
    home = tmp / "home"
    copy_install(installed, home)
    damage(home)
    code, fails = doctor(home)
    if area is None:
        check(case, fails == [], fails)
        return
    check(f"{case}: one FAIL line names it, the exit is 1",
          code == 1 and any(a == area and text in t for a, t in fails), (code, fails))
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("CREW_")}, "HOME": str(home)}
    real = subprocess.run([str(home / ".agent/bin/crew-doctor.py"), "--offline"],
                          capture_output=True, text=True, env=env)
    check(f"{case}: the installed command, run as a process, exits 1", real.returncode == 1, real.stdout[-600:])


def claude_memory_entry(home: Path, folder: str) -> None:
    """One auto-memory entry in the second config dir, under project folder `folder`."""
    memory = home / ".claude-work" / "projects" / folder / "memory"
    memory.mkdir(parents=True)
    (memory / "feedback_lesson.md").write_text("---\ntype: feedback\n---\nA lesson.\n", encoding="utf-8")


@pytest.mark.parametrize("case, damage, level, words", [
    ("auto-memory off everywhere", lambda home: None, "ok", ("auto-memory off",)),
    ("the user's own true",
     lambda home: edit_json(home / ".claude/settings.json", lambda d: d.update(autoMemoryEnabled=True)),
     "WARN", ("~/.claude/settings.json", "autoMemoryEnabled")),
    ("an entry to import", lambda home: claude_memory_entry(home, re.sub(r"[^A-Za-z0-9]", "-", str(home))),
     "note", ("~/.claude-work:", "import-claude --config-dir")),
    ("an entry for review", lambda home: claude_memory_entry(home, "-gone"),
     "note", ("~/.claude-work:", "delete or move")),
])
def test_doctor_auto_memory(installed: Path, tmp: Path, case: str, damage: Callable[[Path], object],
                            level: str, words: tuple[str, ...]) -> None:
    """A user's `true` is a WARN, entries to import or to review are notes, each naming its dir; none counts."""
    home = tmp / "home"
    copy_install(installed, home)
    damage(home)
    done = cli(DOCTOR, "--offline", env={"HOME": str(home), "CREW_MEMORY_DIR": None})
    lines = [line.split(None, 2) for line in done.stdout.splitlines() if len(line.split(None, 2)) == 3]
    machine = any(found[0] == "FAIL" and found[1] in ("tools", "gh") for found in lines)
    check(f"{case}: a {level} memory line names the dir, no other FAIL, and the exit counts only FAIL lines",
          any(found[:2] == [level, "memory"] and all(word in found[2] for word in words) for found in lines)
          and not any(found[0] == "FAIL" and found[1] not in ("tools", "gh") for found in lines)
          and done.returncode == (1 if machine else 0), done.stdout)
