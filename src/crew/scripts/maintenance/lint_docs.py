"""The README's generated blocks and the release files.

One generator: `command_table` reads the router's rows (a row marked "not a stage" goes to the
standalone table), the routed skill's or agent's `description` and the `routes` in `tools.json`;
`crew-lint.py --commands` prints both tables (`crew help`) and `--write-readme` writes them and the
counts between the README's `generated:` markers. Rules: `readme-*-current`, `release-files`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from crew.lib.files import atomic_write
from crew.lib.markdown import frontmatter
from crew.scripts.maintenance.lint_catalog import installed_tool_names

Finding = tuple[str, int, str, str]
README = "README.md"
ROUTER_ROW = re.compile(r"^\|\s*`crew [^`]+`")
CELL = re.compile(r"(?<!\\)\|")
VERB = re.compile(r"`(crew [^`]+)`")
MEMBER = re.compile(r"\bcrew-[a-z0-9-]+\b")
TOOL = re.compile(r"~/\.agent/bin/(crew-[a-z0-9-]+\.(?:py|sh))")

# A description's routing tail (who triggers it, how it is launched) is not what the command does.
ROUTING_TAIL = re.compile(r"\s*(?:Triggers?:|Alias:|Dispatched\b|Launched\b).*$", re.DOTALL)
# A leading "Use when ..." clause says when to load the prompt, also not what the command does.
USE_WHEN = re.compile(r"^Use when [^.;:]*[.;:]\s*")
FIRST_SENTENCE = re.compile(r"^(.+?\.)(?=\s|$)", re.DOTALL)
# A router row outside the pipeline: `(quarterly, not a stage)` puts it in the standalone table.
NOT_A_STAGE = re.compile(r"\(\s*(?:([^(),]*?),\s*)?not a stage\s*\)")
# What a release needs: release-please owns VERSION, CHANGELOG.md and the tags from its manifest.
RELEASE_FILES = (
    "VERSION",
    "CHANGELOG.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "release-please-config.json",
    ".release-please-manifest.json",
    ".github/workflows/release-please.yml",
    ".github/pull_request_template.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
)


def router_rows(root: Path) -> list[tuple[str, str, str]]:
    """`(trigger cell, crew verb, handler cell)` for each routing-table row, in table order."""
    router = root / "rules/crew-router.mdc"
    if not router.is_file():
        router = root / ".cursor/rules/crew-router.mdc"
    if not router.is_file():
        return []
    rows = []
    for line in router.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in CELL.split(line.strip())[1:-1]]
        if ROUTER_ROW.match(line) and len(cells) >= 2:
            rows.append((cells[0], VERB.search(cells[0]).group(1), cells[1]))
    return rows


def tool_routes(root: Path) -> dict[str, tuple[str, str]]:
    """`crew verb -> (command basename, summary)` from the `routes` of each catalog command."""
    try:
        data = json.loads((root / "src/crew/tools.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        verb: (entry["name"], summary) for entry in data.get("tools", []) if isinstance(entry, dict) for verb, summary in (entry.get("routes") or {}).items()
    }


def member_description(root: Path, handler: str) -> str | None:
    """The first sentence of the routed skill's or agent's `description`, without its routing tail."""
    for name in MEMBER.findall(handler):
        for path in (root / ".cursor/skills" / name / "SKILL.md", root / ".cursor/agents" / f"{name}.md"):
            if path.is_file():
                found = str((frontmatter(path.read_text(encoding="utf-8"))[0] or {}).get("description") or "")
                text = USE_WHEN.sub("", ROUTING_TAIL.sub("", found).strip())
                sentence = FIRST_SENTENCE.match(text)
                text = sentence.group(1) if sentence else text
                return text[:1].upper() + text[1:] or None
    return None


def command_rows(root: Path, standalone: bool = False) -> tuple[list[tuple[str, str]], list[str]]:
    """`(command, what it does)` per router row in one table, and one problem per row with no description."""
    routes = tool_routes(root)
    rows, problems = [], []
    for trigger, verb, handler in router_rows(root):
        outside = NOT_A_STAGE.search(handler)
        if bool(outside) != standalone:
            continue
        tool = TOOL.search(handler)
        if tool:
            name, summary = routes.get(verb, ("", ""))
            description = summary if name == tool.group(1) else None
        else:
            description = member_description(root, handler)
        if not description:
            where = f"a `routes` entry on {tool.group(1)} in tools.json" if tool else "a skill or agent with a description"
            problems.append(f"`{verb}` has no description: add {where}")
        qualifier = (outside.group(1) or "").strip() if outside else ""
        if description and qualifier:
            description = f"{qualifier[:1].upper()}{qualifier[1:]}: {description[:1].lower()}{description[1:]}"
        rows.append((trigger, description or "—"))
    return rows, problems


def command_table(root: Path, standalone: bool = False) -> str:
    """The everyday (or, with `standalone`, the outside-the-pipeline) command table."""
    rows, _ = command_rows(root, standalone)
    return "\n".join(["| Command | What it does |", "|---|---|", *(f"| {cmd} | {what} |" for cmd, what in rows)])


def help_text(root: Path) -> str:
    """What `crew help` prints: the everyday table, then the standalone one."""
    return f"{command_table(root)}\n\nStandalone, not a pipeline stage:\n\n{command_table(root, standalone=True)}"


def counts_line(root: Path) -> str:
    """The crew's size, counted from the tree."""
    agents = sorted((root / ".cursor/agents").glob("*.md"))
    crew = [path for path in agents if path.name.startswith("crew-")]
    skills = sorted((root / ".cursor/skills").glob("*/SKILL.md"))
    commands, installed = len(router_rows(root)), len(installed_tool_names(root))
    return f"{len(crew)} crew agents (orchestrators and workers), {len(agents) - len(crew)} personas, {len(skills)} skills, {commands} `crew` commands and {installed} installed commands."


def blocks(root: Path) -> dict[str, str]:
    return {"commands": command_table(root), "standalone": command_table(root, standalone=True), "counts": counts_line(root)}


# The rule a stale block reports under: both command tables are `readme-commands-current`.
BLOCK_RULES = {"commands": "readme-commands-current", "standalone": "readme-commands-current", "counts": "readme-counts-current"}


def markers(name: str) -> tuple[str, str]:
    return f"<!-- generated:{name} (crew-lint.py --write-readme) -->", f"<!-- /generated:{name} -->"


def block_span(text: str, name: str) -> tuple[int, int] | None:
    """The offsets of the text between a block's markers, or None when either marker is missing."""
    start, end = markers(name)
    begin = text.find(start)
    finish = text.find(end, begin + len(start)) if begin >= 0 else -1
    return (begin + len(start), finish) if finish >= 0 else None


def write_readme(root: Path) -> list[str]:
    """Rewrite every generated block, atomically and only when one changed; returns the blocks with no markers."""
    path = root / README
    generated = blocks(root)
    if not path.is_file():
        return list(generated)
    original = text = path.read_text(encoding="utf-8")
    missing = []
    for name, body in generated.items():
        span = block_span(text, name)
        if span is None:
            missing.append(name)
            continue
        text = text[: span[0]] + "\n" + body + "\n" + text[span[1] :]
    if text != original:
        atomic_write(path, text)
    return missing


def lint_readme(root: Path) -> list[Finding]:
    """Each generated README block equals what the generator prints now."""
    path = root / README
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    findings: list[Finding] = []
    for name, body in blocks(root).items():
        rule = BLOCK_RULES[name]
        span = block_span(text, name)
        if span is None:
            findings.append((README, 1, rule, f"no `{markers(name)[0]}` block"))
        elif text[span[0] : span[1]].strip("\n") != body:
            line = text.count("\n", 0, span[0]) + 1
            findings.append((README, line, rule, f"the {name} block is stale; run crew-lint.py --write-readme"))
    problems = command_rows(root)[1] + command_rows(root, standalone=True)[1]
    findings.extend((README, 1, "readme-commands-current", problem) for problem in problems)
    return findings


def lint_release_files(root: Path) -> list[Finding]:
    """The release files exist, VERSION equals the manifest, and release-please starts from a bootstrap commit.

    With no tag and no `bootstrap-sha`, release-please would build its first release from all of history.
    """
    findings: list[Finding] = [(name, 1, "release-files", f"{name} is missing") for name in RELEASE_FILES if not (root / name).is_file()]
    try:
        config = json.loads((root / "release-please-config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        config = None
    if isinstance(config, dict) and not config.get("bootstrap-sha"):
        findings.append(("release-please-config.json", 1, "release-files", "no bootstrap-sha: the first release would cover the whole history"))
    try:
        recorded = json.loads((root / ".release-please-manifest.json").read_text(encoding="utf-8")).get(".")
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except (OSError, json.JSONDecodeError, AttributeError):
        return findings
    if recorded != version:
        findings.append(("VERSION", 1, "release-files", f"VERSION {version} differs from the manifest's {recorded}"))
    return findings
