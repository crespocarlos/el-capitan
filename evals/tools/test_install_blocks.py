#!/usr/bin/env python3
"""What install.sh writes into the harness config, and `crew-doctor.py`'s check of it.

The block helpers are `.claude/install_blocks.py`, the module install.sh runs, so a change that breaks
idempotency, removal or user prose fails here first. The permission rules (the claude-code manifest's) must not let an
allow rule shadow an ask rule (the outcome would depend on evaluation order), gate commands must prompt, and the
settings merge of the claude-code adapter's fragment retires a rule an earlier install added and the fragment dropped
while keeping the user's own. The doctor runs against a fake HOME installed by install.sh, with a fake `gh` first on
PATH.
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
from cli_runner import load as cli_load
from cli_runner import run as cli

from crew.harness import adapters, claude_code

# The fixture installs into a fake HOME: more than the suite's 60 s per test on a loaded runner.
pytestmark = pytest.mark.timeout(300)
PROJECT = Path(__file__).resolve().parents[2]
INSTALL = PROJECT / "install.sh"
MERGE = PROJECT / ".claude" / "merge_claude_settings.py"
BLOCKS = PROJECT / ".claude" / "install_blocks.py"
DOCTOR = PROJECT / "src" / "crew" / "maintenance" / "crew_doctor.py"
MEMORY = "<!-- el-capitan:memory -->\nMEMORY\n<!-- /el-capitan:memory -->"
IMPORTS = "<!-- el-capitan:imports -->\n@~/.claude/el-capitan/x.md\n<!-- /el-capitan:imports -->"
SEEDED = "# a\n\n<!-- el-capitan:memory -->\nstale\n<!-- /el-capitan:memory -->\n\n# b\n"


def check(name: str, condition: bool, detail: object = "") -> None:
    assert condition, f"{name}: {detail}"


def fragment(tmp: Path) -> Path:
    """The claude-code adapter's settings fragment, the source install merges, written to a file."""
    path = tmp / "fragment.json"
    path.write_text(claude_code.render(PROJECT, tmp)[".claude/settings.json"][1], encoding="utf-8")
    return path


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
          "<!-- el-capitan:memory -->" in both and "@~/.claude/el-capitan/x.md" in both
          and upsert(upsert(both, "memory", MEMORY), "imports", IMPORTS) == both)
    removed = remove(remove(both, "memory"), "imports")
    check("removing both blocks gives back the text around them", removed == "# a\n\n# b", repr(removed))
    generated = blocks.global_rule_imports(PROJECT)
    expected: list[str] = []
    for target in re.findall(r"^@(\S+\.mdc?)$", (PROJECT / ".claude/CLAUDE.md").read_text(), re.M):
        expected += [] if target in expected else [target]
    check("the generated imports block is fenced and imports exactly the project file's rules",
          re.findall(r"^@(\S+)$", generated, re.M) == expected and generated.startswith("<!-- el-capitan:imports -->")
          and generated.rstrip().endswith("<!-- /el-capitan:imports -->"), generated)


def broken_claude_md(blocks: ModuleType) -> str:
    """The file an older install left: a marker mentioned in prose became the block start, opening a code span."""
    imports = blocks.global_rule_imports(PROJECT)
    return f"# Shared rules\n\nRule imports are managed: `install.sh` writes the `{imports}\n{blocks.MEMORY}\n"


def test_block_marker_in_prose(tmp: Path) -> None:
    """A marker counts only at the start of a line; install repairs the older mid-line block once, with a backup."""
    blocks, home = load_blocks(), tmp / "home"
    prose = "Install writes the `<!-- el-capitan:memory -->` block.\n"
    check("a marker in prose is not a block, so the block is appended after it",
          blocks.upsert(prose, "memory", MEMORY) == prose + "\n" + MEMORY + "\n")
    for target in re.findall(r"^@~/(\S+)$", blocks.global_rule_imports(PROJECT), re.M):
        (home / target).parent.mkdir(parents=True, exist_ok=True)
        (home / target).write_text("rule\n", encoding="utf-8")
    claude = home / ".claude/CLAUDE.md"
    claude.parent.mkdir(exist_ok=True)
    claude.write_text(broken_claude_md(blocks), encoding="utf-8")
    blocks.install(home, PROJECT)
    repaired = claude.read_text(encoding="utf-8")
    backups = list(claude.parent.glob("CLAUDE.md.bak.*"))
    check("install repairs it with one backup of the original, and its imports load",
          len(backups) == 1 and backups[0].read_text() == broken_claude_md(blocks)
          and "Rule imports are managed" in repaired and blocks.import_problems(home, PROJECT) == [], repaired)
    blocks.install(home, PROJECT)
    check("a second install changes nothing and writes no backup",
          claude.read_text() == repaired and len(list(claude.parent.glob("CLAUDE.md.bak.*"))) == 1)
    (home / ".claude/el-capitan/personal.md").unlink()
    check("an import naming a missing file is reported",
          blocks.import_problems(home, PROJECT) == ["@~/.claude/el-capitan/personal.md names a missing file"])


def command_of(rule: str) -> str | None:
    """The command a `Bash(<command> *)` rule names (it may contain spaces), or None for a non-Bash rule."""
    if not rule.startswith("Bash(") or not rule.endswith(")"):
        return None
    body = rule[len("Bash("):-1]
    return body[:-2] if body.endswith(" *") else body.rstrip(":*")


def test_permission_rules() -> None:
    permissions = adapters.manifest("claude-code")["permissions"]
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
    gates = (f"{task} mark-approved /tmp/t", f"{task} mark-done /tmp/t", f"{task} mark-done /tmp/t --force",
             f"{task} restore-status /tmp/t", f"{task} restore-status /tmp/t --accept note")
    covered = [c for c in allow for command in gates if command == c or command.startswith(c + " ")]
    check("no allow rule covers Gate 1, Gate 2 or restore-status, so each prompts", not covered, covered)
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


def test_project_settings_register_no_hooks(tmp: Path) -> None:
    """Claude Code and Cursor load the checkout's `.claude/settings.json` as project settings, and Cursor runs a hook
    each file registers, so it holds no hooks; its other keys are the adapter's fragment's, which install merges."""
    project = json.loads((PROJECT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    template = json.loads(fragment(tmp).read_text(encoding="utf-8"))
    check("the project settings register no hooks", "hooks" not in project, sorted(project))
    check("the project settings keep the template's other keys",
          project == {key: value for key, value in template.items() if key != "hooks"}, sorted(project))


def test_settings_merge(tmp: Path) -> None:
    """The installer retires the ask rules on task specs an earlier install recorded and the template dropped (the file
    guard's status rule holds a Status move), and keeps the user's own rules."""
    spec_rules = ["Write(~/.agent/tasks/*/SPEC.md)", "Edit(~/.agent/tasks/*/SPEC.md)"]
    user = {"permissions": {"allow": ["Bash(git *)", "Bash(my-own *)"],
                            "ask": [*spec_rules, "Edit(~/.agent/tasks/**)", "Edit(~/.claude/**)"]},
            "hooks": {}}
    home, dest = tmp / "home", tmp / "home" / "cfg" / "settings.json"
    dest.parent.mkdir(parents=True)
    dest.write_text(json.dumps(user), encoding="utf-8")
    section = f"claude_settings:{dest.parent}"
    (home / ".agent").mkdir()
    manifest = {"version": 1, section: {"rules": {"ask": spec_rules}}}
    (home / ".agent/install-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = subprocess.run([sys.executable, str(MERGE), str(fragment(tmp)), str(dest), "--manifest", str(home)],
                            capture_output=True, text=True)
    merged = json.loads(dest.read_text(encoding="utf-8"))["permissions"]
    recorded = json.loads((home / ".agent/install-manifest.json").read_text(encoding="utf-8"))[section]
    check("the merge retires the recorded ask rules, forgets them, and keeps the user's own rules",
          result.returncode == 0 and merged["ask"] == ["Edit(~/.agent/tasks/**)", "Edit(~/.claude/**)"]
          and "Bash(my-own *)" in merged["allow"] and not recorded.get("rules", {}).get("ask"),
          (result.stderr[-200:], merged, recorded))


def test_settings_merge_task_directory(tmp: Path) -> None:
    """The task directory, written as an absolute path under HOME, and its Edit rule are merged beside the
    user's own; the unmerge of the record takes back only them."""
    home, dest = tmp / "home", tmp / "home" / "cfg" / "settings.json"
    dest.parent.mkdir(parents=True)
    before = {"permissions": {"allow": ["Bash(my-own *)"], "additionalDirectories": ["~/mine"]}}
    dest.write_text(json.dumps(before), encoding="utf-8")
    merged = subprocess.run([sys.executable, str(MERGE), str(fragment(tmp)), str(dest), "--manifest", str(home)],
                            capture_output=True, text=True, env={**os.environ, "HOME": str(home)})
    permissions = json.loads(dest.read_text(encoding="utf-8"))["permissions"]
    unmerge = ("import json, sys, merge_claude_settings as m; d = json.load(open(sys.argv[1])); "
               "r = next(v for k, v in json.load(open(sys.argv[2])).items() if k.startswith('claude_settings')); "
               "print(json.dumps(m.unmerge(d, r, json.load(open(sys.argv[3])), print)['permissions']))")
    undone = subprocess.run([sys.executable, "-c", unmerge, str(dest), str(home / ".agent/install-manifest.json"),
                             str(fragment(tmp))], capture_output=True, text=True, cwd=MERGE.parent)
    check("both keys merged beside the user's directory, and uninstall leaves only the user's",
          merged.returncode == 0 and permissions["additionalDirectories"] == ["~/mine", f"{home}/.agent/tasks"]
          and "Edit(~/.agent/tasks/**)" in permissions["allow"] and undone.returncode == 0
          and json.loads(undone.stdout.splitlines()[-1]) == before["permissions"],
          (merged.stderr[-300:], permissions, undone.stdout[-300:], undone.stderr[-300:]))


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
    merged = subprocess.run([sys.executable, str(MERGE), str(fragment(tmp)), str(dest), "--manifest", str(home), *flags],
                            capture_output=True, text=True)
    value = json.loads(dest.read_text(encoding="utf-8")).get("autoMemoryEnabled")
    unmerge = ("import json, sys, merge_claude_settings as m; d = json.load(open(sys.argv[1])); "
               "r = next(v for k, v in json.load(open(sys.argv[2])).items() if k.startswith('claude_settings')); "
               "print(json.dumps(m.unmerge(d, r, json.load(open(sys.argv[3])), print).get('autoMemoryEnabled')))")
    undone = subprocess.run([sys.executable, "-c", unmerge, str(dest), str(home / ".agent/install-manifest.json"),
                             str(fragment(tmp))], capture_output=True, text=True, cwd=MERGE.parent)
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
    del data["hooks"]["beforeShellExecution"]


def drop_claude_guard(data: dict) -> None:
    for entry in data["hooks"]["PreToolUse"]:
        entry["hooks"] = [hook for hook in entry["hooks"] if "PreToolUse" not in hook["command"]]


def tilde_hook(home: Path) -> None:
    edit_json(home / ".claude/settings.json", lambda data: data["hooks"]["Stop"].append(
        {"hooks": [{"type": "command", "command": "bash ~/.claude/hooks/tilde-gone.sh"}]}))


PLUGIN_HOOKS = ".cursor/plugins/local/el-capitan/hooks/hooks.json"


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
    ("broken link", lambda home: (home / ".claude/el-capitan/gone.md").symlink_to(PROJECT / "rules/gone.mdc"),
     "links", "gone.md"),
    ("edited block", lambda home: (home / ".claude/CLAUDE.md").write_text(STALE_BLOCK),
     "blocks", "CLAUDE.md memory block stale"),
    ("imports in a code span", lambda home: (home / ".claude/CLAUDE.md").write_text(broken_claude_md(load_blocks())),
     "imports", "inside a code span or fence"),
    ("a hook rule edited after install", lambda home: (home / ".agent/hooks/guard/shell.sh").write_text("exit 0\n"),
     "harness", "~/.agent/hooks/guard/shell.sh differs from its render"),
    ("missing script, ~/ form", tilde_hook,
     "hooks", "Claude Code (~/.claude): registered hook scripts are missing: ~/.claude/hooks/tilde-gone.sh"),
    ("missing hook in the second config dir",
     lambda home: edit_json(home / ".claude-work/settings.json", drop_claude_guard),
     "hooks", "Claude Code (~/.claude-work): "),
    ("second config dir without agents", lambda home: (home / ".claude-work/agents").unlink(),
     "links", "~/.claude-work: not linked to ~/.claude: agents"),
    ("wrong matcher", lambda home: edit_json(home / ".claude/settings.json", unmatch),
     "hooks", "missing or different PreToolUse Bash"),
    ("a Cursor plugin registration missing", lambda home: edit_json(home / PLUGIN_HOOKS, drop_guard),
     "harness", "~/.cursor/plugins/local/el-capitan/hooks/hooks.json differs from its render"),
    ("over-limit state", over_limit, "state", "tasks 0.0 MB (limit 0 MB); crew gc"),
    ("telemetry", telemetry, "state", "crew-task.py gc --only telemetry --apply"),
    ("bad config", lambda home: (home / ".agent/config.json").write_text(BAD_CONFIG), "config", "artifact_days"),
    ("a rendered agent stale after a config change",
     lambda home: (home / ".agent/config.json").write_text(json.dumps({"mcp": {"docs": ["docs-a"]}})),
     "harness", "reviewer-adversarial.md differs from its render"),
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


WANTED = {"docs": ["docs-a", "docs-b"], "code_search": ["search-x"]}


def servers(*names: str, **projects: dict) -> str:
    """An MCP config: `names` at user level, and each project path's entry (its own keys as given)."""
    return json.dumps({"mcpServers": {name: {} for name in names},
                       "projects": {f"@TMP@/w/{key}": value for key, value in projects.items()}})


def own(*names: str) -> dict:
    """A projects entry holding its own servers."""
    return {"mcpServers": {name: {} for name in names}}


def origin(url: str, *paths: str) -> dict[str, str]:
    """A git config whose `remote.origin.url` is `url` in each path; CREW is the remote the temp task names."""
    return {f"{path}/.git/config": f'[core]\n\tbare = false\n[remote "origin"]\n\turl = {url}\n' for path in paths}


def plugin(*installs: dict, **others: list) -> dict[str, str]:
    """~/.claude's installed_plugins.json listing the `srch` plugin with these installs, and other plugins by name."""
    named = {f"{name}@mkt": value for name, value in others.items()}
    listing = {"version": 2, "plugins": {"srch@mkt": list(installs), **named}}
    return {"home/.claude/plugins/installed_plugins.json": json.dumps(listing)}


def crew_project(path: str, url: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    """A projects entry at `path` that disables docs-a (so a matched project WARNs), its repository's origin at
    `url` (the config one level up for a `/sub` path), and any extra files."""
    entry = {path.removeprefix("w/"): {"disabledMcpServers": ["docs-a"]}}
    return {"home/.claude.json": servers("docs-a", "search-x", **entry), **origin(url, path.removesuffix("/sub")),
            **(extra or {})}


CREW = "git@example.com:o/crew.git"
CREW_WARN = "docs server (docs-a, docs-b) missing for 1 of 1 projects with crew work: /w/"
DOCS, SEARCH = "docs server (docs-a, docs-b)", "code search (search-x)"
PLUGIN_WANTED = {"docs": ["docs-a"], "code_search": ["plugin_srch_srch"]}
PLUGIN_SEARCH = "code search (plugin_srch_srch)"
UNCHECKED = ("note", "servers from claude.ai connectors are not checked")
NONE_NOTE = ("note", "no configured MCP servers in ~/.claude-work: crew agents in sessions on it use text search")
REPO = {"repo/.git/HEAD": "ref\n", **origin(CREW, "repo"),
        "repo/.mcp.json": json.dumps({"mcpServers": {"docs-b": {}, "search-x": {}}})}
# The repo project of the unapproved case: docs-b approved but disabled, search-x never approved.
UNAPPROVED = {"enabledMcpjsonServers": ["docs-b"], "disabledMcpjsonServers": ["docs-b"]}
# (case, files under the temp root (`@TMP@` is that root), `mcp` config (None: invalid), CLAUDE_CONFIG_DIR under it,
#  cwd under it, (level, text) lines that must appear, texts no line may contain). HOME is `home/`, with
#  `home/.claude` and one task whose remote is CREW; every config file is a temp one; the temp root is cut from lines.
MCP_CASES = (
    ("both servers at user level",
     {"home/.claude.json": servers("docs-a", "search-x"), "home/.cursor/mcp.json": servers("docs-b", "search-x")},
     WANTED, None, ".", [("ok", f"Claude Code ~/.claude: {DOCS} at user level"), ("ok", f"Cursor: {SEARCH}")],
     ["WARN"]),
    ("the docs server only in a projects entry",
     {"home/.claude.json": servers("search-x", kibana=own("docs-a"), other={}), **origin(CREW, "w/kibana", "w/other")},
     WANTED, None, ".",
     [("WARN", f"{DOCS} missing for 1 of 2 projects with crew work: /w/other"),
      ("ok", f"{SEARCH} at user level"),
      ("WARN", "Cursor: docs server missing: none of docs-a, docs-b in ~/.cursor/mcp.json")],
     ["/w/kibana"]),
    ("a project without crew work is not checked",
     {"home/.claude.json": servers("docs-a", "search-x", other={"disabledMcpServers": ["docs-a"]}),
      **origin("git@example.com:o/elsewhere.git", "w/other")}, WANTED, None, ".",
     [("ok", f"{DOCS} at user level")], ["WARN Claude", "/w/other"]),
    ("a worktree resolves to its main repository's origin",
     {"home/.claude.json": servers("docs-a", "search-x", wt={"disabledMcpServers": ["docs-a"]}),
      "w/wt/.git": "gitdir: ../main/.git/worktrees/wt\n", "w/main/.git/worktrees/wt/commondir": "../..\n",
      **origin(CREW, "w/main")}, WANTED, None, ".",
     [("WARN", f"{DOCS} missing for 1 of 1 projects with crew work: /w/wt")], []),
    ("an insteadOf rule in ~/.gitconfig rewrites the origin before the match",
     crew_project("w/iof", "crew:crew.git", {"home/.gitconfig": '[url "git@example.com:o/"]\n\tinsteadOf = crew:\n'}),
     WANTED, None, ".", [("WARN", CREW_WARN + "iof")], []),
    ("an origin without the .git suffix matches", crew_project("w/bare", "git@example.com:o/crew"),
     WANTED, None, ".", [("WARN", CREW_WARN + "bare")], []),
    ("an https origin matches the task's ssh remote", crew_project("w/https", "https://example.com/o/crew.git"),
     WANTED, None, ".", [("WARN", CREW_WARN + "https")], []),
    ("a project in a subdirectory reads the repository above it", crew_project("w/up/sub", CREW),
     WANTED, None, ".", [("WARN", CREW_WARN + "up/sub")], []),
    ("a server only in the repo's approved .mcp.json",
     {**REPO, "repo/.cursor/mcp.json": servers("docs-a", "search-x"),
      "home/.claude/settings.json": json.dumps({"enableAllProjectMcpServers": True})}, WANTED, None, "repo",
     [("ok", f"{DOCS} in every project (1)"), ("ok", "Cursor: docs server (docs-a)")], ["WARN"]),
    ("an unapproved or disabled repo server does not count; the primary dir keeps its WARNs",
     {**REPO, "home/.claude.json": json.dumps({"projects": {"@TMP@/repo": UNAPPROVED}})}, WANTED, None, "repo",
     [("WARN", f"{DOCS} missing for 1 of 1 projects with crew work"),
      ("WARN", f"{SEARCH} missing for 1 of 1 projects with crew work")], ["no configured MCP servers"]),
    ("an extra config dir with no configured server gets one note",
     {"home/.claude.json": servers("docs-a", "search-x"), "home/.claude-work/.claude.json": servers()},
     WANTED, "home/.claude-work", ".", [NONE_NOTE], ["WARN Claude"]),
    ("a user-level server disabled in a project",
     {"home/.claude.json": servers("docs-a", "search-x", kibana={"disabledMcpServers": ["docs-a"]}),
      **origin(CREW, "w/kibana")}, WANTED, None, ".",
     [("WARN", f"{DOCS} missing for 1 of 1 projects with crew work: /w/kibana"),
      ("ok", f"{SEARCH} at user level")], []),
    ("a plugin installed at user scope provides its server",
     {"home/.claude.json": servers("docs-a"), **plugin({"scope": "user"})}, PLUGIN_WANTED, None, ".",
     [("ok", f"Claude Code ~/.claude: {PLUGIN_SEARCH} at user level")], ["WARN Claude"]),
    ("a plugin disabled in settings.json provides nothing",
     {"home/.claude.json": servers("docs-a"), **plugin({"scope": "user"}),
      "home/.claude/settings.json": json.dumps({"enabledPlugins": {"srch@mkt": False}})}, PLUGIN_WANTED, None, ".",
     [("WARN", f"Claude Code ~/.claude: {PLUGIN_SEARCH} missing at user level")], []),
    ("no plugins file: the plugin server is missing",
     {"home/.claude.json": servers("docs-a")}, PLUGIN_WANTED, None, ".",
     [("WARN", f"Claude Code ~/.claude: {PLUGIN_SEARCH} missing at user level")], []),
    ("without manifests plugin_a_b_srv belongs to a_b, the longest name, not a",
     {"home/.claude.json": servers("docs-a"), **plugin(a=[{"scope": "user"}], a_b=[{"scope": "user"}]),
      "home/.claude/settings.json": json.dumps({"enabledPlugins": {"a_b@mkt": False}})},
     {"docs": ["docs-a"], "code_search": ["plugin_a_b_srv"]}, None, ".",
     [("WARN", "code search (plugin_a_b_srv) missing at user level")], []),
    ("a manifest names the servers exactly: a prefix match it does not declare is missing",
     {"home/.claude.json": servers("docs-a"), **plugin({"scope": "user", "installPath": "@TMP@/inst"}),
      "inst/.claude-plugin/marketplace.json": json.dumps({"plugins": [{"name": "srch", "mcpServers": {"other": {}}}]})},
     PLUGIN_WANTED, None, ".", [("WARN", f"{PLUGIN_SEARCH} missing at user level")], []),
    ("a project's .claude/settings.json disables a user plugin there",
     {"home/.claude.json": servers("docs-a", kibana={}), **origin(CREW, "w/kibana"), **plugin({"scope": "user"}),
      "w/kibana/.claude/settings.json": json.dumps({"enabledPlugins": {"srch@mkt": False}})}, PLUGIN_WANTED, None, ".",
     [("WARN", f"{PLUGIN_SEARCH} missing for 1 of 1 projects with crew work: /w/kibana")], []),
    ("a project's settings.local.json enables a plugin the user level disabled",
     {"home/.claude.json": servers("docs-a", kibana={}), **origin(CREW, "w/kibana"), **plugin({"scope": "user"}),
      "home/.claude/settings.json": json.dumps({"enabledPlugins": {"srch@mkt": False}}),
      "w/kibana/.claude/settings.local.json": json.dumps({"enabledPlugins": {"srch@mkt": True}})},
     PLUGIN_WANTED, None, ".", [("ok", f"{PLUGIN_SEARCH} in every project (1)")], ["WARN Claude"]),
    ("the docs server missing in a second config dir",
     {"home/.claude.json": servers("docs-a", "search-x"), "home/.claude-work/.claude.json": servers("search-x")},
     WANTED, "home/.claude-work", ".",
     [("ok", f"Claude Code ~/.claude: {DOCS} at user level"),
      ("WARN", f"Claude Code ~/.claude-work: {DOCS} missing at user level"),
      ("ok", f"Claude Code ~/.claude-work: {SEARCH} at user level")],
     [f"~/.claude: {DOCS} missing"]),
    ("CLAUDE_CONFIG_DIR at ~/.claude reads the file inside it",
     {"home/.claude.json": servers("docs-a", "search-x"), "home/.claude/.claude.json": servers("search-x")},
     WANTED, "home/.claude", ".", [("WARN", f"Claude Code ~/.claude: {DOCS} missing at user level")], []),
    ("a config dir that does not exist is skipped",
     {"home/.claude.json": servers("docs-a", "search-x")}, WANTED, "home/.claude-gone", ".",
     [("ok", f"Claude Code ~/.claude: {DOCS} at user level")], ["~/.claude-gone"]),
    ("no mcp section", {"home/.claude.json": servers()}, {"docs": [], "code_search": []}, None, ".",
     [("note", 'no MCP server is checked; add "mcp": {"docs": ["<server>"]')], ["Claude Code", "Cursor", UNCHECKED[1]]),
    ("an invalid mcp section", {"home/.claude.json": servers()}, None, None, ".",
     [("note", "the mcp section of ~/.agent/config.json is not valid")], ["Claude Code", "no mcp section"]),
)


@pytest.mark.parametrize("case, files, wanted, config_dir, cwd, expected, absent", MCP_CASES,
                         ids=[row[0] for row in MCP_CASES])
def test_doctor_mcp(tmp: Path, case: str, files: dict[str, str], wanted: dict | None, config_dir: str | None, cwd: str,
                    expected: list[tuple[str, str]], absent: list[str]) -> None:
    """Each capability is found by the configured names at user level, from an enabled plugin, per crew project or
    in the approved repo file, minus disabled servers, in each existing config dir; a gap is a WARN naming the server
    and the place, never a FAIL and never a setup instruction."""
    cli_load(DOCTOR)
    from crew.maintenance.doctor_mcp import check_mcp
    (tmp / "home" / ".claude").mkdir(parents=True)
    files = {"home/.agent/tasks/t1/.task-id": json.dumps({"repo_remote_url": CREW}), **files}
    for name, text in files.items():
        (tmp / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp / name).write_text(text.replace("@TMP@", str(tmp)), encoding="utf-8")
    environ = {"CLAUDE_CONFIG_DIR": str(tmp / config_dir)} if config_dir else {}
    lines = check_mcp(tmp / "home", wanted, tmp / cwd, environ)
    shown = [(line.level, line.text.replace(str(tmp), "")) for line in lines]
    check(f"{case}: the expected lines appear, none is a FAIL or says 'add it', and the absent texts do not",
          all(any(level == got and text in body for got, body in shown) for level, text in expected)
          and all(level != "FAIL" and "add it" not in body for level, body in shown)
          and not any(text in f"{level} {body}" for text in absent for level, body in shown), shown)
    check(f"{case}: one note with no names configured, else the unchecked sources named last",
          len(shown) == 1 if not wanted or not any(wanted.values()) else shown[-1] == UNCHECKED, shown)


def tools_lines(home: Path, directory: str) -> dict[str, str]:
    """The `tools:` line of each regular (rendered) agent file under `directory` of HOME."""
    files = [path for path in sorted((home / directory).glob("*.md")) if path.is_file() and not path.is_symlink()]
    return {path.name: next(line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("tools:")) for path in files}


def home_env(home: Path) -> dict[str, str]:
    """The environment for an install into `home`: no crew or config-dir variable from the caller."""
    drop = ("CREW_", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_JOB_DIR")
    return {**{k: v for k, v in os.environ.items() if not k.startswith(drop)}, "HOME": str(home)}


def install_with_config(home: Path, mcp: dict | None) -> None:
    (home / ".agent").mkdir(parents=True, exist_ok=True)
    (home / ".agent" / "config.json").write_text(json.dumps({"mcp": mcp} if mcp else {}), encoding="utf-8")


AGENT_DIRS = (".claude/agents", ".cursor/plugins/local/el-capitan/agents")


def test_rendered_agents(tmp: Path) -> None:
    """Install renders each read-only agent's allowlist from the mcp config, for Claude Code and in the Cursor plugin,
    and records the files; the session-start refresh re-renders the stale ones; a re-install with no mcp section
    renders the plain list; uninstall removes them."""
    home = tmp / "home"
    install_with_config(home, {"docs": ["docs-a", "docs-b"], "code_search": ["search-x"]})
    config, env = home / ".agent" / "config.json", home_env(home)
    templated = sorted(path.name for path in (PROJECT / ".cursor" / "agents").glob("*.md") if "{{mcp_servers}}" in path.read_text())
    servers_part = ", mcp__docs-a__*, mcp__docs-b__*, mcp__search-x__*"
    done = subprocess.run(["bash", str(INSTALL)], capture_output=True, text=True, env=env)
    recorded = json.loads((home / ".agent/install-manifest.json").read_text())["rendered"]
    for directory in AGENT_DIRS:
        lines = tools_lines(home, directory)
        check(f"{directory}: every templated agent is a rendered file ending with the three servers, recorded",
              done.returncode == 0 and sorted(lines) == templated and len(templated) == 12
              and lines["reviewer-adversarial.md"] == f"tools: Read, Grep, Glob{servers_part}"
              and lines["reviewer-probe.md"] == f"tools: Read, Grep, Glob, Write, Bash{servers_part}"
              and lines["crew-pr-resolver.md"] == f"tools: Read, Grep, Glob, Bash{servers_part}"
              and (home / directory / "crew-builder.md").is_symlink()
              and all(f"{directory}/{name}" in recorded for name in templated), (done.stderr[-400:], lines))
    config.write_text(json.dumps({"mcp": {"docs": ["docs-a"]}}), encoding="utf-8")
    hook = PROJECT / ".claude" / "hooks" / "agents-refresh.sh"
    first, second = (subprocess.run(["bash", str(hook)], capture_output=True, text=True, env=env, timeout=60) for _ in range(2))
    check("the session-start refresh re-renders every stale file once, in one line, and exits 0",
          first.returncode == second.returncode == 0 and second.stdout == "" and first.stderr == ""
          and first.stdout.strip() == "agents: re-rendered 24 stale agent file(s)"
          and tools_lines(home, AGENT_DIRS[1])["reviewer-adversarial.md"] == "tools: Read, Grep, Glob, mcp__docs-a__*", (first, second))
    config.write_text(json.dumps({"gc": {"artifacts_days": 7}}), encoding="utf-8")
    done = subprocess.run(["bash", str(INSTALL)], capture_output=True, text=True, env=env)
    lines = tools_lines(home, AGENT_DIRS[0])
    check("a re-install with no mcp section renders the plain list",
          done.returncode == 0 and lines["reviewer-adversarial.md"] == "tools: Read, Grep, Glob"
          and lines["crew-pr-resolver.md"] == "tools: Read, Grep, Glob, Bash" and sorted(lines) == templated, lines)
    done = subprocess.run(["bash", str(INSTALL), "--uninstall"], capture_output=True, text=True, env=env)
    check("uninstall removes the rendered files", done.returncode == 0 and not any((home / d).exists() for d in AGENT_DIRS),
          done.stdout[-600:])


def test_render_rules(tmp: Path) -> None:
    """Server names keep only the characters a tool id keeps, matched whole; only the frontmatter `tools:` line is
    templated, so the placeholder in prose is text."""
    cli_load(DOCTOR)
    from crew.task.task_gc import ConfigError, load_config
    for bad in ("elastic.docs", "docs\n", "docs a"):
        install_with_config(tmp, {"docs": [bad]})
        check(f"{bad!r} is rejected by install and by the config", adapters.mcp_server_names(tmp)[0] == []
              and adapters.mcp_server_names(tmp)[1] is not None)
        with pytest.raises(ConfigError):
            load_config(tmp / ".agent")
    source = "---\nname: x\ntools: Read, Grep, Glob  # {{mcp_servers}}\n---\nWrite `{{mcp_servers}}` in prose.\n"
    prose = "---\nname: y\n---\nThe line ends in `  # {{mcp_servers}}`.\n"
    check("only the frontmatter line is rendered, and an agent with the placeholder only in prose is not templated",
          adapters.render_agent(source, ["s"]) == source.replace("Glob  # {{mcp_servers}}", "Glob, mcp__s__*")
          and adapters.render_agent(source, []) == source.replace("Glob  # {{mcp_servers}}", "Glob")
          and adapters.render_agent(prose, ["s"]) == prose and adapters.placeholder_line(prose) is None)


def test_mcp_config_section(tmp: Path) -> None:
    """The shared defaults name no server; a list of names is accepted and anything else is a config error."""
    cli_load(DOCTOR)
    from crew.task.task_gc import ConfigError, load_config
    check("the defaults are empty", load_config(tmp)["mcp"] == {"docs": [], "code_search": []})
    (tmp / "config.json").write_text(json.dumps({"mcp": {"docs": ["docs-a"]}}), encoding="utf-8")
    check("a list of names is merged over the defaults",
          load_config(tmp)["mcp"] == {"docs": ["docs-a"], "code_search": []})
    for bad in ({"docs": "docs-a"}, {"docs": [""]}, {"search": ["x"]}):
        (tmp / "config.json").write_text(json.dumps({"mcp": bad}), encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(tmp)


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
