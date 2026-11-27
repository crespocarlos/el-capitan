#!/usr/bin/env python3
"""What install.sh writes into the harness config: the managed CLAUDE.md blocks and the permission rules.

The block helpers are extracted from install.sh's heredoc rather than duplicated, so a change that
breaks idempotency or eats user prose fails here first. The permission rules must not let an allow
rule shadow an ask rule (the outcome would depend on evaluation order), gate commands must prompt, and
the installer's settings merge retires a broad rule the template narrowed while keeping the user's own.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
INSTALL = PROJECT / "install.sh"
SETTINGS = PROJECT / ".claude" / "settings.json"
MERGE = SETTINGS.parent / "merge_claude_settings.py"
MEMORY = "<!-- el-capitan:memory -->\nMEMORY\n<!-- /el-capitan:memory -->"
IMPORTS = "<!-- el-capitan:imports -->\n@~/.cursor/rules/x.mdc\n<!-- /el-capitan:imports -->"
SEEDED = "# a\n\n<!-- el-capitan:memory -->\nstale\n<!-- /el-capitan:memory -->\n\n# b\n"


def check(name: str, condition: bool, detail: object = "") -> None:
    assert condition, f"{name}: {detail}"


def load_helpers() -> dict:
    """Exec only the install.sh heredoc's pure helpers, stopping before any filesystem work."""
    text = INSTALL.read_text()
    marker = 'python3 - "$HOME" "$SCRIPT_DIR" <<\'PY\'\n'
    start = text.index(marker) + len(marker)
    end = text.index("imports = global_rule_imports()", start)
    namespace: dict = {"__name__": "install_heredoc", "__builtins__": __builtins__}
    prelude = f"import sys\nsys.argv = ['x', 'unused', {str(PROJECT)!r}]\n"
    exec(compile(prelude + text[start:end], "install.sh:helpers", "exec"), namespace)
    return namespace


def test_managed_blocks() -> None:
    ns = load_helpers()
    upsert, global_imports = ns["upsert"], ns["global_rule_imports"]
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
    generated = global_imports()
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
