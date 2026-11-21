#!/usr/bin/env python3
"""Reference integrity in documents: paths, installed names, rules, agents, routing, swallowed calls.

Every reference a prompt makes has to resolve, or the failure lands at the next `crew` command
rather than at review time: a backticked repo path that was renamed, a `~/.agent/bin/<name>` the
installer no longer links, an `.mdc` or agent that does not exist, a `crew <verb>` with no routing
row, or a command whose failure is hidden by `2>/dev/null`.
"""
from __future__ import annotations

import re
from pathlib import Path

from lint_files import line_no, rel

# The memory CLI: a swallowed memory failure is a defect, so its call sites are checked by name.
MEMORY_COMMANDS = ("crew-mem.py",)
REPO_PATH = re.compile(r"`((?:\.agent|\.cursor|\.claude|rules|evals)/[^`\s]*)`")
INSTALLED = re.compile(r"~/.agent/bin/([\w.-]+)")
RULE_FILE = re.compile(r"([\w-]+\.mdc)")
AGENT_REF = re.compile(r"(?:subagent_type:\s*|@)([\w-]+)")
ROUTING_ROW = re.compile(r"\|\s*`crew ")
# A prompt asks a command for repo facts instead of running git itself: a bare `git rev-parse` or
# `git branch --show-current` prints nothing when it fails, and the prompt then acts on an empty
# variable. `crew-repo-info.py` is the one answer. Mutations stay raw only where the user approved
# them, so `git commit`/`add`/`push` are not flagged. `crew-diff.sh` and `guard-shell.sh` are
# exempt: the first emits diff content, the second is the hook that reads git in order to police it.
GIT_FACT = re.compile(
    r"`?git\s+(?:-\S+\s+)*(?:rev-parse|branch\s+--show-current|branch\s+-vv|branch\s+--merged"
    r"|remote\s+get-url|worktree\s+list)|\$\(git\s+(?:-\S+\s+)*(?:rev-parse|branch|remote)")
GIT_FACT_EXEMPT = ("crew-diff.sh", "guard-shell.sh")
Findings = list[tuple[str, int, str, str]]


def lint_repo_paths(root: Path, paths: list[Path]) -> Findings:
    """Flag backticked repo-relative paths that no longer exist."""
    findings: Findings = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in REPO_PATH.finditer(text):
            target = match.group(1)
            if any(char in target for char in "<>*${}"):
                continue
            if not (root / target.rstrip("/")).exists():
                findings.append((rel(root, path), line_no(text, match.start()), "stale-path",
                                 f"{target} does not exist"))
    return findings


def lint_installed_names(
    root: Path, all_files: list[Path], installed_names: set[str]
) -> Findings:
    """Every `~/.agent/bin/<name>` reference resolves to a cataloged command."""
    findings: Findings = []
    for path in all_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        name = rel(root, path)
        for match in INSTALLED.finditer(text):
            script = match.group(1)
            if script not in installed_names:
                findings.append((name, line_no(text, match.start()), "missing-script",
                                 f"{script} is not in the .agent/tools tree"))
    return findings


def routing_commands(router_text: str) -> set[str]:
    """The `crew <command>` verbs the router recognizes, from both its table and its prose."""
    routed = set(re.findall(r"`(crew [^`|]+?)(?:`|\s)", router_text))
    routed.update(re.findall(r"\|\s*`(crew [^`]+)`", router_text))
    return {
        match.group(1)
        for command in routed
        if (match := re.match(r"crew\s+([a-z-]+)", command))
    }


def lint_swallowed_calls(name: str, lines: list[str]) -> Findings:
    """Flag a memory or agent command whose failure is hidden by `2>/dev/null` or `|| true`.

    State and gate commands must surface failure; audit logging is the one legitimate exception
    because it cannot change a pipeline decision. A hook that must never block a session opts out
    with a `crew-lint: allow-swallow` comment on its own line.
    """
    findings: Findings = []
    for line, value in enumerate(lines, 1):
        if any(command in value for command in MEMORY_COMMANDS) and (
            "2>/dev/null" in value or "|| true" in value
        ):
            findings.append((name, line, "swallowed-call", "memory command failure is hidden"))
        if "~/.agent/bin/" in value and "crew-metric.py" not in value and (
            "2>/dev/null" in value or re.search(r"\|\|\s*true", value)
        ):
            exempt = "crew-lint: allow-swallow" in value
            if not exempt and not re.search(r"\|\|\s*(echo|printf|exit)", value):
                findings.append((name, line, "swallowed-call",
                                 "agent command failure is hidden"))
    return findings


def lint_document_refs(
    root: Path, path: Path, text: str, name: str, rules: set[str],
    agents: set[str], routed_commands: set[str], router: Path,
) -> Findings:
    """The per-document references: rules, agents, routing, frontmatter, relative references."""
    findings: Findings = []
    for match in RULE_FILE.finditer(text):
        candidate = match.group(1)
        if candidate not in rules and candidate != path.name:
            findings.append((name, line_no(text, match.start()), "missing-rule-file",
                             f"{candidate} is not a rule file"))
    for match in AGENT_REF.finditer(text):
        agent = match.group(1)
        if agent.startswith("crew-") and agent not in agents:
            findings.append((name, line_no(text, match.start()), "missing-agent",
                             f"{agent} is not in .cursor/agents"))
    if name != "rules/crew-router.mdc":
        for line, value in enumerate(text.splitlines(), 1):
            for command in re.findall(r"\bcrew\s+([a-z-]+)", value):
                if command in {"member", "command", "commands", "triggers", "protocol"}:
                    continue
                if command not in routed_commands:
                    findings.append((name, line, "unrouted-command",
                                     f"crew {command} has no routing row"))
    findings.extend(lint_swallowed_calls(name, text.splitlines()))
    if path.suffix == ".md" and ("/agents/" in name or path.name == "SKILL.md"):
        if text.startswith("---"):
            frontmatter = text.split("---", 2)[1]
            for key in ("name:", "description:"):
                if key not in frontmatter:
                    findings.append((name, 1, "bad-frontmatter", f"frontmatter lacks {key[:-1]}"))
        for match in re.finditer(r"\]\((references/[^)#]+)\)", text):
            if not (path.parent / match.group(1)).is_file():
                findings.append((name, line_no(text, match.start()), "missing-reference",
                                 f"{match.group(1)} does not exist"))
    if path != router and name != ".cursor/agents/crew-reviewer.md":
        for match in ROUTING_ROW.finditer(text):
            findings.append((name, line_no(text, match.start()), "routing-drift",
                             "routing tables belong only in crew-router.mdc"))
    return findings


def lint_documents(
    root: Path, all_files: list[Path], installed_names: set[str], rules: set[str],
    router: Path,
) -> Findings:
    """The per-document checks over every in-scope file, plus the installed-name sweep."""
    findings: Findings = []
    agents = {path.stem for path in (root / ".cursor/agents").glob("*.md")}
    routed_commands = routing_commands(router.read_text(encoding="utf-8") if router.exists() else "")
    findings.extend(lint_installed_names(root, all_files, installed_names))
    for path in all_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        name = rel(root, path)
        for match in re.finditer(r"tasks/(?:\$REPO|<repo>)", text):
            findings.append((name, line_no(text, match.start()), "stale-task-path",
                             "use crew-resolve-task-dir.py instead"))
        findings.extend(lint_document_refs(root, path, text, name, rules, agents,
                                           routed_commands, router))
        findings.extend(lint_git_facts(name, text))
    return findings


def lint_git_facts(name: str, text: str) -> Findings:
    """Flag a prompt that runs git to learn the repo root, branch, remote, or worktree list.

    Those questions have one answer, `crew-repo-info.py`, and the shell snippets a prompt used to
    carry failed silently: `$(git rev-parse ...)` on a broken checkout yields an empty string that
    the next step treats as a real value. Diff and log reads are not flagged — they read commit
    output, not a repo fact — and neither are approved mutations.
    """
    if name.endswith(GIT_FACT_EXEMPT):
        return []
    return [(name, line_no(text, match.start()), "git-fact-in-prompt",
             "ask crew-repo-info.py (or crew-worktree.py for worktrees) instead of running git")
            for match in GIT_FACT.finditer(text)]
