#!/usr/bin/env python3
"""Guard the managed-block upsert that install.sh applies to ~/.claude/CLAUDE.md.

The helpers are extracted from install.sh's heredoc rather than duplicated, so a change to the
installer that breaks idempotency or eats user prose fails here first.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / "install.sh"
PROJECT = TOOL.parent
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"pass: {name}")
        return
    FAILED.append(name)
    print(f"FAIL: {name}{': ' + detail if detail else ''}")


def load_helpers() -> dict:
    """Exec only the install.sh heredoc's pure helpers, stopping before any filesystem work.

    Everything above the `imports = global_rule_imports()` call is a definition or a constant, so
    cutting there yields the real implementation with no side effects.
    """
    text = TOOL.read_text()
    marker = 'python3 - "$HOME" "$SCRIPT_DIR" <<\'PY\'\n'
    start = text.index(marker) + len(marker)
    end = text.index("imports = global_rule_imports()", start)
    namespace: dict = {"__name__": "install_heredoc"}
    # The heredoc binds `home` and `source` from argv; the helpers read only `source`.
    namespace["__builtins__"] = __builtins__
    exec(compile(f"import sys\nsys.argv = ['x', 'unused', {str(PROJECT)!r}]\n"
                 + text[start:end], "install.sh:helpers", "exec"), namespace)
    return namespace


def main() -> int:
    ns = load_helpers()
    upsert, global_imports = ns["upsert"], ns["global_rule_imports"]
    body = "<!-- el-capitan:memory -->\nMEMORY\n<!-- /el-capitan:memory -->"

    once = upsert("# notes\n", "memory", body)
    check("appends a block to a file without one", "<!-- el-capitan:memory -->" in once)
    check("preserves surrounding text on append", "# notes" in once)

    seeded = "# a\n\n<!-- el-capitan:memory -->\nstale\n<!-- /el-capitan:memory -->\n\n# b\n"
    first = upsert(seeded, "memory", body)
    second = upsert(first, "memory", body)
    third = upsert(second, "memory", body)
    check("upsert is idempotent", first == second == third, "repeated installs differ")
    check("stale block is replaced", "stale" not in first)
    check("text before the block survives", "# a" in first)
    check("text after the block survives", "# b" in first)
    check("no trailing blank-line growth", not first.endswith("\n\n\n"), repr(first[-8:]))

    imports_block = ("<!-- el-capitan:imports -->\n@~/.cursor/rules/x.mdc\n"
                     "<!-- /el-capitan:imports -->")
    both = upsert(upsert(seeded, "memory", body), "imports", imports_block)
    check("memory block survives an imports upsert", "<!-- el-capitan:memory -->" in both)
    check("imports block is added", "@~/.cursor/rules/x.mdc" in both)
    again = upsert(upsert(both, "memory", body), "imports", imports_block)
    check("two-block document is idempotent", again == both)

    generated = global_imports()
    expected: list[str] = []
    for target in re.findall(r"@(\S+\.mdc)", (PROJECT / ".claude/CLAUDE.md").read_text()):
        if target not in expected:
            expected.append(target)
    produced = re.findall(r"^@(\S+)$", generated, re.M)
    check("generated imports match the project file", produced == expected,
          f"{produced} != {expected}")
    check("generated block is fenced",
          generated.startswith("<!-- el-capitan:imports -->")
          and generated.rstrip().endswith("<!-- /el-capitan:imports -->"))

    # The reason the block exists: every always-on rule must reach Claude Code from any repo.
    always_on = [r for r in sorted((PROJECT / "rules").glob("*.mdc"))
                 if "alwaysApply: true" in r.read_text()]
    check("there are always-on rules to propagate", bool(always_on))
    for rule in always_on:
        check(f"always-on rule reaches Claude Code: {rule.name}", f"/{rule.name}" in generated)

    if FAILED:
        print(f"\n{len(FAILED)} failed")
        return 1
    print("\nall install-block checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
