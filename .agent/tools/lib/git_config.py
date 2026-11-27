"""Git config read from files, without running git: the repository root, its git directory, and the origin URL.

For checks that must not depend on git being on PATH or working (`crew doctor`). Every reader returns None or []
when a file is missing or unreadable; nothing raises.
"""
from __future__ import annotations

import re
from pathlib import Path


def repo_root(cwd: Path) -> Path | None:
    """The nearest directory at or above `cwd` holding `.git`, without running git."""
    return next((path for path in (cwd, *cwd.parents) if (path / ".git").exists()), None)


def config_rows(path: Path) -> list[tuple[str, str, str]]:
    """(section, key, value) rows of one git config file, the section as `name` or `name "sub"`; [] when unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows, section = [], ""
    for line in text.splitlines():
        if header := re.match(r'\s*\[\s*([\w.-]+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\]', line):
            name, sub = header.group(1).lower(), header.group(2)
            section = f'{name} "{sub}"' if sub is not None else name
        elif entry := re.match(r"\s*([\w-]+)\s*=\s*(.*?)\s*$", line):
            rows.append((section, entry.group(1).lower(), entry.group(2).strip('"')))
    return rows


def git_dir_of(project: Path) -> Path | None:
    """The git directory holding the config for `project` or its nearest parent with `.git`; a worktree's `.git`
    file is followed to the main repository through its `commondir`."""
    top = repo_root(project)
    if top is None:
        return None
    dot = top / ".git"
    if not dot.is_file():
        return dot
    try:
        pointer = re.match(r"gitdir:\s*(.+)", dot.read_text(encoding="utf-8"))
        git_dir = top / pointer.group(1).strip() if pointer else None
        if git_dir and (git_dir / "commondir").is_file():
            git_dir = git_dir / (git_dir / "commondir").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return git_dir


def origin_url(project: Path, home: Path) -> str | None:
    """`remote.origin.url` as git would use it, read without running git: the repository's config, with the
    `url.<base>.insteadOf` rules of that config and the user's (`~/.gitconfig`, `~/.config/git/config`) applied."""
    git_dir = git_dir_of(project)
    rows = config_rows(git_dir / "config") if git_dir else []
    urls = [value for section, key, value in rows if section == 'remote "origin"' and key == "url"]
    if not urls:
        return None
    rules = [(value, section[5:-1]) for config in (home / ".gitconfig", home / ".config" / "git" / "config")
             for section, key, value in config_rows(config) + rows
             if section.startswith('url "') and key == "insteadof"]
    matches = [(prefix, base) for prefix, base in rules if urls[-1].startswith(prefix)]
    if not matches:
        return urls[-1]
    prefix, base = max(matches, key=lambda rule: len(rule[0]))
    return base + urls[-1][len(prefix):]
