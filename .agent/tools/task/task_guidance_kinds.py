"""Repository guidance ranked per agent kind under one byte cap per kind: the one place these defaults live.

Sections (`## `, or `### ` ones standing alone) fill the cap in order: those naming one of the agent's paths first,
then by the kind's topics, then the rest, nearest file first, so only the cap drops anything. Each file's text before
its first heading fits first; the last section that does not fit is cut at a line. The note names every section the
cap dropped or cut, with its file, and goes beside the text in the prompt.
"""
from __future__ import annotations

import re
from pathlib import Path

# A topic is a set of heading words, matched at a word start and case-insensitively.
TOPICS = {
    "verify": r"test|verif|run\b|command|bootstrap|gate|lint|\bci\b|check|build|validat",
    "edit": r"edit|commit",
    "code": r"convention|style|naming|language|import|exit|output|error|logging",
    "layout": r"layout|structure|module|architect|package|catalog|stack|area|feature|director",
    "contract": r"contract|status|security|privacy|auth\b|authenticat|authoriz|data|migration|hook|environment"
                r"|\benv\b|api\b|schema|setting",
    "prompt": r"prompt|author|agent|skill|glossary|writing",
    "product": r"\bux\b|\bui\b|frontend|design|navigation|copy|glossary|accessib|user|screen",
}
# Each kind: its topics in priority order (the order sections fill the cap), and its cap in bytes.
KINDS: dict[str, tuple[tuple[str, ...], int]] = {
    "reviewer-adversarial": (("contract", "code", "edit"), 16000),
    "reviewer-architecture": (("layout", "contract"), 12000),
    "reviewer-code-quality": (("code", "edit", "verify", "layout"), 16000),
    "reviewer-product-flow": (("product", "contract"), 12000),
    "reviewer-prompt-quality": (("prompt", "edit"), 14000),
    "builder": (("verify", "edit", "contract", "code", "layout"), 24000),
    "explorer": (("verify", "layout", "code"), 10000),
    "resolver": (("verify", "edit", "code"), 14000),
}
# These kinds rank the prompt-authoring rules second when a path they work on is a prompt file.
PROMPT_PROMOTED = ("builder", "explorer", "resolver")
PROMPT_PATH = re.compile(r"(^|/)(\.cursor|\.claude|rules|agents|skills|prompts?)/.*\.mdc?$|prompt")
MIN_CUT = 200  # bytes: below this, a section that does not fit is dropped rather than cut to a stub
RECOVERY = "Read that file for a dropped section you need."


def kinds() -> list[str]:
    return sorted(KINDS)


def topics_for(kind: str, paths: list[str] | None = None) -> tuple[str, ...]:
    topics, _ = KINDS[kind]
    if kind in PROMPT_PROMOTED and any(PROMPT_PATH.search(path) for path in paths or []):
        return (topics[0], "prompt", *[topic for topic in topics[1:] if topic != "prompt"])
    return topics


def sections(content: str, level: str = "## ") -> tuple[str, list[tuple[str, str]]]:
    """`(text before the first heading of `level`, [(heading, section text)])`."""
    parts = re.split(rf"(?m)^(?={level})", content)
    head = "" if parts and parts[0].startswith(level) else parts.pop(0)
    return head, [(part.splitlines()[0][len(level):].strip(), part) for part in parts]


def rank(heading: str, topics: tuple[str, ...]) -> int:
    """The index of the first topic the heading names; `len(topics)` (after every topic) when none does."""
    for index, topic in enumerate(topics):
        if re.search(rf"\b(?:{TOPICS[topic]})", heading, re.I):
            return index
    return len(topics)


DIRECTORY = re.compile(r"(?<![\w./-])((?:[\w.-]+/)+)")  # a path written with a trailing slash: `db/migrations/`
NOT_NAMED = 2  # relevance tier of a section that names none of the agent's paths


def relevance(text: str, paths: list[str]) -> tuple[int, int]:
    """`(tier, -hits)`: tier 0 when the text names one of `paths` verbatim, 1 when it names a directory that is a
    prefix of one, else `NOT_NAMED`; hits count those mentions. A bare basename never counts: a tree listing every
    file name would otherwise outrank the rule that governs the file."""
    files = sum(len(re.findall(rf"(?<![\w./-]){re.escape(path)}(?![\w/-])", text)) for path in paths if "/" in path)
    folders = sum(1 for found in DIRECTORY.findall(text) if any(path.startswith(found) for path in paths))
    tier = 0 if files else 1 if folders else NOT_NAMED
    return tier, -(files + folders)


def units(content: str, topics: tuple[str, ...], paths: list[str]) -> list[tuple]:
    """`[(relevance, rank, position, parent, heading, text)]` for one file. Sections rank by relevance tier, then by
    topic, then by how often they name `paths`; a `## ` section that names a path, or that no topic names, is ranked
    by its `### ` sections instead, each under `parent` (its heading and opening text, written once)."""
    found = []
    for position, (heading, text) in enumerate(sections(content)[1]):
        level, named = rank(heading, topics), relevance(text, paths)
        intro, subs = sections(text, "### ")
        if not subs or (level < len(topics) and named[0] == NOT_NAMED):
            found.append((named, level, (position, 0), "", heading, text))
            continue
        found += [(relevance(body, paths), rank(sub, topics), (position, index), intro, f"{heading} > {sub}", body)
                  for index, (sub, body) in enumerate(subs, 1)]
    return found


def label(path: str, files: dict[str, str]) -> str:
    """`path` relative to the directory of the root-most file, for the note."""
    base = Path(next(iter(files))).parent
    try:
        return str(Path(path).relative_to(base))
    except ValueError:
        return path


def cut(text: str, room: int) -> str:
    """At most `room` bytes of `text`, ending at a line."""
    kept = text.encode("utf-8")[:max(room, 0)].decode("utf-8", errors="ignore")
    return kept[:kept.rfind("\n") + 1] if "\n" in kept else ""


def size(text: str) -> int:
    return len(text.encode("utf-8"))


def narrow(kind: str, files: dict[str, str], paths: list[str] | None = None,
           said: list[str] | None = None) -> tuple[dict[str, str], str]:
    """`({path: kept text}, note)`; `files` in root-to-nearest order, as `collect` returns them; `paths` the agent's
    repository-relative paths (changed or task files). Raises KeyError for an unknown kind. `said` are lines the
    caller adds to the note; the note is "" when it has nothing to say."""
    topics, cap = topics_for(kind, paths), KINDS[kind][1]
    heads = {path: sections(content)[0] if sections(content)[1] else content for path, content in files.items()}
    ranked = sorted((named[0], level, named[1], nearness, path, position, parent, heading, text)
                    for nearness, (path, content) in enumerate(reversed(list(files.items())))
                    for named, level, position, parent, heading, text in units(content, topics, paths or []))
    room, over = cap, []
    for path in reversed(list(files)):  # a file's text before its first heading fits first, nearest file first
        if size(heads[path]) > room:
            heads[path] = cut(heads[path], room) + "[cut at the cap]\n"
            over.append(f"{label(path, files)}: the text before its first heading (cut)")
        room = max(room - size(heads[path]), 0)
    kept: dict[str, list[tuple]] = {path: [] for path in files}
    opened: set[tuple[str, int]] = set()  # (path, section) whose parent text is already counted
    for _tier, _level, _hits, _near, path, position, parent, heading, text in ranked:
        head = "" if (path, position[0]) in opened else parent
        name = f"{label(path, files)}: {heading}"
        if size(head + text) <= room:
            room -= size(head + text)
        elif room > MIN_CUT + size(head) and not any(item.endswith("(cut)") for item in over):
            text, room = cut(text, room - size(head)) + "[cut at the cap]\n", 0
            over.append(f"{name} (cut)")
        else:
            over.append(name)
            continue
        opened.add((path, position[0]))
        kept[path].append((position, parent, text))
    return {path: (heads[path] + joined(kept[path])).strip() for path in files}, note(cap, over, said or [])


def joined(kept: list[tuple]) -> str:
    """The kept sections in file order, each parent text once before its first kept `### ` section."""
    out, last = [], ""
    for _position, parent, text in sorted(kept):
        if parent and parent != last:
            out.append(parent)
        last = parent
        out.append(text)
    return "".join(out)


def note(cap: int, over: list[str], said: list[str]) -> str:
    lines = list(said)
    if over:
        lines.append(f"Dropped at the {cap}-byte cap: {'; '.join(over)}. {RECOVERY}")
    return "\n".join(lines)


def render(kind: str, files: dict[str, str], paths: list[str] | None = None,
           said: list[str] | None = None) -> tuple[str, str]:
    """`(block, note)`: the kept files, each under `## From \\`<path>\\``, inside one `<guidance>` element; the note,
    when there is one, is the line after the opening tag. `("", "")` with no file. `dispatch-bytes` measures the
    element's bounds."""
    if not files:
        return "", ""
    narrowed, told = narrow(kind, files, paths, said)
    body = "".join(f"## From `{path}`\n\n{text}\n\n" for path, text in narrowed.items() if text)
    cap = KINDS[kind][1]
    return f'<guidance kind="{kind}" cap="{cap}">\n' + (f"{told}\n\n" if told else "") + body + "</guidance>\n", told
