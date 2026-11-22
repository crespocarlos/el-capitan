"""The permission config must not let an allow rule shadow an ask rule.

An `allow` and an `ask` matching the same command makes the outcome depend on evaluation order
instead of intent, which is how a guard starts making things worse. This checks the property
directly: no allow rule's command prefix may be a prefix of any ask rule's command prefix.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[2] / ".claude" / "settings.json"
MERGE = SETTINGS.parent / "merge_claude_settings.py"
FAILED: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"pass: {name}")
        return
    FAILED.append(name)
    print(f"FAIL: {name}{': ' + str(detail) if detail else ''}")


def command_of(rule: str) -> str | None:
    """The command a `Bash(...)` rule names, or None for a non-Bash rule.

    A rule is `Bash(<command> *)` where `<command>` may itself contain spaces, so the prefix is
    everything before the trailing wildcard, not the first word.
    """
    if not rule.startswith("Bash(") or not rule.endswith(")"):
        return None
    body = rule[len("Bash("):-1]
    return body[:-2] if body.endswith(" *") else body.rstrip(":*")


def merge_cases() -> None:
    """The installer must retire a broad rule when the template narrows it."""
    scratch = Path(tempfile.mkdtemp(prefix="merge-perm-"))
    try:
        (scratch / "dest.json").write_text(json.dumps({"permissions": {
            "allow": ["Bash(git *)", "Bash(my-own *)"],
            "ask": ["Edit(~/.agent/tasks/**)", "Write(~/.agent/tasks/**)", "Edit(~/.claude/**)"],
        }, "hooks": {}}), encoding="utf-8")
        result = subprocess.run(["python3", str(MERGE), str(SETTINGS), str(scratch / "dest.json")],
                                capture_output=True, text=True)
        check("the merge succeeds", result.returncode == 0, result.stderr[:200])
        merged = json.loads((scratch / "dest.json").read_text(encoding="utf-8"))["permissions"]
        check("a broad task rule is retired by the narrow one",
              "Edit(~/.agent/tasks/**)" not in merged["ask"]
              and "Edit(~/.agent/tasks/*/SPEC.md)" in merged["ask"], merged["ask"])
        check("an unrelated user ask rule survives", "Edit(~/.claude/**)" in merged["ask"],
              merged["ask"])
        check("an unrelated user allow rule survives", "Bash(my-own *)" in merged["allow"],
              merged["allow"])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main() -> int:
    permissions = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]
    allow = [c for c in (command_of(r) for r in permissions.get("allow", [])) if c]
    ask = [c for c in (command_of(r) for r in permissions.get("ask", [])) if c]

    check("the config parses and has an allow list", bool(allow), len(allow))
    check("no ask rule uses the literal-colon form", not any(
        ":" in r[len("Bash("):-1].split(" ")[0] for r in permissions.get("ask", [])
        if r.startswith("Bash(") and r.endswith(")")), permissions.get("ask"))

    shadowed = [(a, s) for s in ask for a in allow if a.startswith(s) or s.startswith(a)]
    check("no allow rule shadows an ask rule", not shadowed, shadowed)
    check("an ask rule on a task directory targets a file, not its whole tree",
          all(not r.endswith("/**") for r in permissions.get("ask", [])
              if ".agent/tasks" in r), permissions.get("ask"))

    check("the bin directory is not allowed wholesale",
          not any(c == "~/.agent/bin/*" for c in allow), [c for c in allow if "agent/bin" in c])
    check("the review findings command is allowed outright, with the space form",
          any(c == "~/.agent/bin/crew-review-findings.py" for c in allow),
          [c for c in allow if "crew-review-findings" in c])
    check("a leading shell assignment is allowed, so it cannot prompt",
          any(c == "R=" or c.endswith("=*") for c in allow), [c for c in allow if "=*" in c])
    check("hook fixtures are allowed without elevation",
          any("fixtures" in c for c in allow), allow)

    merge_cases()
    print("all permission checks passed" if not FAILED else f"permissions: {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
