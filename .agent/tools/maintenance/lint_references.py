"""Reference integrity in documents, and the handoff trailer grammar.

A backticked repo path, an installed `~/.agent/bin/<name>`, an `.mdc` or agent, and a `crew <verb>`
must resolve; a failure hidden by `2>/dev/null` is reported. A trailer is one `> Next:` line, last,
naming a command the router recognizes (none is required; one inside backticks does not count).
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
# A prompt asks a command for repo facts instead of running git: a failing `git rev-parse` prints
# nothing and the prompt then acts on an empty variable. Mutations and diff reads stay raw.
# `.claude/hooks/` is exempt as a tree: a hook is not a prompt, it inspects the exact tree the tool
# call names rather than the session's, and it already handles a failure on every one of those calls.
GIT_FACT = re.compile(
    r"`?git\s+(?:-\S+\s+)*(?:rev-parse|branch\s+--show-current|branch\s+-vv|branch\s+--merged"
    r"|remote\s+get-url|worktree\s+list)|\$\(git\s+(?:-\S+\s+)*(?:rev-parse|branch|remote)")
GIT_FACT_EXEMPT = ("crew-diff.sh",)
GIT_FACT_EXEMPT_PREFIX = ".claude/hooks/"
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

    Those questions have one answer, `crew-repo-info.py`; a shell snippet fails silently:
    `$(git rev-parse ...)` on a broken checkout yields an empty string that
    the next step treats as a real value. Diff and log reads are not flagged — they read commit
    output, not a repo fact — and neither are approved mutations. Hook scripts are exempt: they are
    not prompts, they inspect the tree their own tool call names, and every one of those calls
    already handles a failure.
    """
    if name.endswith(GIT_FACT_EXEMPT) or name.startswith(GIT_FACT_EXEMPT_PREFIX):
        return []
    return [(name, line_no(text, match.start()), "git-fact-in-prompt",
             "ask crew-repo-info.py (or crew-worktree.py for worktrees) instead of running git")
            for match in GIT_FACT.finditer(text)]


TRAILER = re.compile(r"^\s*> Next: (?P<body>.*)$")
ANY_NEXT = re.compile(r"Next:")
CREW_COMMAND = re.compile(r"`(crew [^`]+)`")
FENCE = re.compile(r"^\s*(```|~~~)")
# `output-formats.md:12`: a PR review's findings are pasted by a person, not handed to a command.
HUMAN_HANDOFF = "paste the bodies from"


def handoff_files(root: Path) -> list[Path]:
    """Every file the grammar governs: skills, agents and their references, and rules."""
    paths: list[Path] = []
    paths.extend(sorted((root / ".cursor/skills").glob("*/SKILL.md")))
    paths.extend(sorted((root / ".cursor/agents").glob("*.md")))
    paths.extend(sorted((root / ".cursor/agents").glob("*/references/*.md")))
    # The shared references load beside every agent, so the grammar governs them too: a trailer rule
    # stated in `dispatch.md` and a stray `Next:` beside it belong to the same contract.
    paths.extend(sorted((root / ".cursor/agents/references").glob("*.md")))
    paths.extend(sorted((root / ".cursor/skills").glob("*/references/*.md")))
    for rule_dir in (root / "rules", root / ".cursor/rules"):
        if rule_dir.is_dir():
            paths.extend(sorted(rule_dir.glob("*.mdc")))
            break
    return [path for path in paths if path.is_file()]


def fenced_lines(text: str) -> list[tuple[int, str]]:
    """Each line with its number, from outside fenced blocks: a fence holds examples, not a handoff."""
    kept: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append((number, line))
    return kept


def prose_lines(text: str) -> list[tuple[int, str]]:
    """The same lines with every `code span` blanked out, so a quoted token is not a handoff.

    A span may wrap across lines — a skill that prints one of three next steps quotes each one — so
    the span is tracked across the whole file rather than matched per line. A span delimited by a run
    of backticks closes only on a run of the same length, which is how a quoted handoff is written
    inside a file that also uses single-backtick spans.
    """
    kept: list[tuple[int, str]] = []
    in_fence = False
    span = 0
    for number, line in enumerate(text.splitlines(), 1):
        if not span and FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        visible: list[str] = []
        index = 0
        while index < len(line):
            char = line[index]
            if char != "`":
                visible.append(" " if span else char)
                index += 1
                continue
            run = len(line) - len(line[index:].lstrip("`"))
            if span == 0:
                span = run
            elif run == span:
                span = 0
            visible.append(" " * run)
            index += run
        kept.append((number, "".join(visible).rstrip()))
    return kept


def trailer_problems(name: str, text: str, verbs: set[str]) -> Findings:
    """The rules for a file that emits a trailer: exactly one, last, and every verb resolvable."""
    lines = fenced_lines(text)
    trailers = [(number, line) for number, line in lines if TRAILER.match(line)]
    if not trailers:
        return []
    if len(trailers) > 1:
        return [(name, number, "handoff-multiple-trailers",
                 f"a file declares one handoff trailer; this is number {index} of {len(trailers)}")
                for index, (number, _) in enumerate(trailers, 1) if index > 1]
    number, line = trailers[0]
    last = next((candidate for candidate, value in reversed(lines) if value.strip()), 0)
    if last != number:
        return [(name, number, "handoff-trailer-not-last",
                 "the trailer must be the file's last non-empty line, or nothing after it runs")]
    body = TRAILER.match(line).group("body")
    named = CREW_COMMAND.findall(body)
    problems: Findings = []
    for command in named:
        verb = command.split()[1]
        if verb not in verbs:
            problems.append((name, number, "handoff-unrouted-command",
                             f"`{command}` has no row in crew-router.mdc"))
    if not named and HUMAN_HANDOFF not in body:
        problems.append((name, number, "handoff-no-command",
                         "a trailer names a `crew <verb>` command, or the documented "
                         f"`{HUMAN_HANDOFF}` action for a PR review"))
    return problems


def stray_next_problems(name: str, text: str, claimed: set[int] | None = None) -> Findings:
    """A file may not carry an unbackticked `Next:` that reads as one, beyond its own trailer.

    `claimed` holds the line numbers the trailer check already accounted for, so a file with one
    trailer is still checked everywhere else: two handoff sentences in one file is the shape this
    rule exists to stop, and treating "has a trailer" as "is done" hid exactly that.
    """
    seen = claimed or set()
    return [(name, number, "handoff-stray-next",
             "`Next:` outside a quoted trailer is not a handoff; wrap the example in backticks")
            for number, line in prose_lines(text)
            if ANY_NEXT.search(line) and number not in seen]


def lint_handoff(root: Path, router: Path) -> Findings:
    """Check every governed file: trailers are well formed, and no stray `Next:` claims to be one."""
    verbs = routing_commands(router.read_text(encoding="utf-8")) if router.exists() else set()
    findings: Findings = []
    for path in handoff_files(root):
        name = rel(root, path)
        text = path.read_text(encoding="utf-8", errors="replace")
        trailers = [number for number, line in fenced_lines(text) if TRAILER.match(line)]
        if trailers:
            findings.extend(trailer_problems(name, text, verbs))
        findings.extend(stray_next_problems(name, text, set(trailers)))
    return findings
