#!/usr/bin/env python3
"""Validate cross-file el-capitan conventions.

Usage: crew-lint.py [--root DIR] [--budget]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def files(root: Path) -> list[Path]:
    patterns = [
        "rules/*.mdc",
        ".cursor/rules/*.mdc",
        ".cursor/agents/**/*.md",
        ".cursor/skills/**/SKILL.md",
        ".cursor/skills/**/references/*.md",
        ".claude/CLAUDE.md",
        ".claude/settings.json",
        ".cursor/hooks.template.json",
        ".claude/hooks/*.sh",
    ]
    result: set[Path] = set()
    for pattern in patterns:
        result.update(path for path in root.glob(pattern) if path.is_file())
    return sorted(result)


def rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def line_no(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def lint(root: Path, budget: bool) -> list[tuple[str, int, str, str]]:
    findings: list[tuple[str, int, str, str]] = []
    all_files = files(root)
    rule_dir = root / "rules"
    rules = (
        {path.name for path in rule_dir.glob("*.mdc")}
        if rule_dir.is_dir()
        else {path.name for path in (root / ".cursor/rules").glob("*.mdc")}
    )
    agents = {path.stem for path in (root / ".cursor/agents").glob("*.md")}
    router = root / "rules/crew-router.mdc"
    if not router.exists():
        router = root / ".cursor/rules/crew-router.mdc"
    router_text = router.read_text() if router.exists() else ""
    routed = set(re.findall(r"`(crew [^`|]+?)(?:`|\s)", router_text))
    routed.update(re.findall(r"\|\s*`(crew [^`]+)`", router_text))
    routed_commands = {
        match.group(1)
        for command in routed
        if (match := re.match(r"crew\s+([a-z-]+)", command))
    }

    for path in all_files:
        text = path.read_text(errors="replace")
        name = rel(root, path)
        for match in re.finditer(r"tasks/(?:\$REPO|<repo>)", text):
            findings.append((name, line_no(text, match.start()), "stale-task-path",
                             "use resolve-task-dir.py instead"))
        for match in re.finditer(r"~/.agent/bin/([\w.-]+)", text):
            script = match.group(1)
            if not (root / ".agent/bin" / script).exists():
                findings.append((name, line_no(text, match.start()), "missing-script",
                                 f"{script} is not in .agent/bin"))
        for match in re.finditer(r"([\w-]+\.mdc)", text):
            candidate = match.group(1)
            if candidate not in rules and candidate != path.name:
                findings.append((name, line_no(text, match.start()), "missing-rule-file",
                                 f"{candidate} is not a rule file"))
        for match in re.finditer(r"(?:subagent_type:\s*|@)([\w-]+)", text):
            agent = match.group(1)
            if agent.startswith("crew-") and agent not in agents:
                findings.append((name, line_no(text, match.start()), "missing-agent",
                                 f"{agent} is not in .cursor/agents"))
        for line, value in enumerate(text.splitlines(), 1):
            if name == "rules/crew-router.mdc":
                continue
            for command in re.findall(r"\bcrew\s+([a-z-]+)", value):
                if command in {"member", "command", "commands", "triggers", "protocol"}:
                    continue
                if command not in routed_commands:
                    findings.append((name, line, "unrouted-command",
                                     f"crew {command} has no routing row"))
            if "mem.py" in value and (
                "2>/dev/null" in value or "|| true" in value
            ):
                findings.append((name, line, "swallowed-call",
                                 "memory command failure is hidden"))
        if path.suffix == ".md" and (
            "/agents/" in name or "/skills/" in name
        ):
            if text.startswith("---"):
                frontmatter = text.split("---", 2)[1]
                for key in ("name:", "description:"):
                    if key not in frontmatter:
                        findings.append((name, 1, "bad-frontmatter",
                                         f"frontmatter lacks {key[:-1]}"))
        if path != router and name != ".cursor/agents/crew-reviewer.md":
            for match in re.finditer(r"\|\s*`crew ", text):
                findings.append((name, line_no(text, match.start()), "routing-drift",
                                 "routing tables belong only in crew-router.mdc"))

    referenced_hooks = ""
    for config in (root / ".claude/settings.json", root / ".cursor/hooks.template.json"):
        if config.exists():
            referenced_hooks += config.read_text(errors="replace")
    for hook in (root / ".claude/hooks").glob("*.sh"):
        if hook.name not in referenced_hooks:
            findings.append((rel(root, hook), 1, "unregistered-hook",
                             "hook is not registered in a settings file"))

    if budget:
        always = 0
        for rule in rule_dir.glob("*.mdc"):
            text = rule.read_text(errors="replace")
            if re.search(r"alwaysApply:\s*true", text):
                always += len(text) // 4
        if always > 5500:
            findings.append(("rules", 1, "budget",
                             f"always-on rules estimate {always} tokens (>5500)"))
        for path in all_files:
            lines = path.read_text(errors="replace").count("\n") + 1
            if ("/agents/" in rel(root, path) or "/skills/" in rel(root, path)) and lines > 500:
                findings.append((rel(root, path), 1, "budget",
                                 f"{lines} lines (>500)"))
        for rule in rules:
            if (root / "rules" / rule).exists() and (root / ".cursor/rules" / rule).exists():
                findings.append((f"rules/{rule}", 1, "budget",
                                 "rule exists under rules and .cursor/rules"))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--budget", action="store_true")
    args = parser.parse_args()
    if not args.root.is_dir():
        print(f"error: root does not exist: {args.root}", file=sys.stderr)
        return 2
    findings = lint(args.root.resolve(), args.budget)
    for path, line, rule, message in findings:
        print(f"{path}:{line}: {rule}: {message}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
