"""The permission config must not let an allow rule shadow an ask rule.

An `allow` and an `ask` matching the same command makes the outcome depend on evaluation order
instead of intent, which is how a guard starts making things worse. This checks the property
directly: no allow rule's command prefix may be a prefix of any ask rule's command prefix.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[2] / ".claude" / "settings.json"
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


def main() -> int:
    permissions = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]
    allow = [c for c in (command_of(r) for r in permissions.get("allow", [])) if c]
    ask = [c for c in (command_of(r) for r in permissions.get("ask", [])) if c]

    check("the config parses and has both lists", bool(allow) and bool(ask), (len(allow), len(ask)))
    check("no ask rule uses the literal-colon form", not any(
        ":" in r[len("Bash("):-1].split(" ")[0] for r in permissions.get("ask", [])
        if r.startswith("Bash(") and r.endswith(")")), permissions.get("ask"))

    shadowed = [(a, s) for s in ask for a in allow if a.startswith(s) or s.startswith(a)]
    check("no allow rule shadows an ask rule", not shadowed, shadowed)

    check("the bin directory is not allowed wholesale",
          not any(c == "~/.agent/bin/*" for c in allow), [c for c in allow if "agent/bin" in c])
    check("the review findings command still asks", any("crew-review-findings" in s for s in ask), ask)
    check("hook fixtures are allowed without elevation",
          any("fixtures" in c for c in allow), allow)

    print("all permission checks passed" if not FAILED else f"permissions: {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
