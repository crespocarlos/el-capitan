"""Install what each adapter's `render()` returns: `python -m crew.harness.harness_install apply|diff <home> <checkout>`,
`refresh <home>` or `show <harness> <path> <home> <checkout>`. `apply` retires the layout before the adapters
(registrations first), writes each link and file, records them (`rendered`), removes a recorded one no adapter renders
and keeps a user's own with one line; a `deny` entry adds tokens to an existing config, a `merge` entry is install.sh's
(`show`). `refresh` re-renders the recorded agent files; `diff` (crew doctor) names each mismatch.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

from crew.harness import adapters
from crew.lib.files import atomic_write

MANIFEST = Path(".agent") / "install-manifest.json"
# Where the layout before the adapters linked rule, agent and hook files (each a directory under HOME).
LEGACY_LINKS = (".cursor/rules", ".cursor/agents", ".claude/hooks")


def entries(checkout: Path, home: Path) -> dict[str, tuple[str, str]]:
    """Every adapter's render plus the shared reference store, by path under HOME."""
    found = adapters.shared(checkout)
    for harness in adapters.IDS:
        found.update(adapters.adapter(harness).render(checkout, home))
    return found


def load(home: Path) -> dict:
    path = home / MANIFEST
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1}


def save(home: Path, manifest: dict) -> None:
    atomic_write(home / MANIFEST, json.dumps(manifest, indent=2) + "\n")


def roots_of(checkout: Path, manifest: dict) -> set[str]:
    return {os.path.realpath(checkout), str(checkout), *manifest.get("checkouts", [])}


def into(link: Path, roots: set[str]) -> bool:
    """True for a link whose target, existing or not, lies in an install checkout."""
    target = os.path.realpath(link)
    return any(target == root or target.startswith(root + os.sep) for root in roots)


def tilde(path: Path, home: Path) -> str:
    return "~/" + str(path.relative_to(home)) if path.is_relative_to(home) else str(path)


def remove(path: Path, home: Path) -> None:
    """Unlink `path`, then each parent it left empty, never above `<home>/<a>/<b>`."""
    path.unlink()
    parent = path.parent
    while len(parent.relative_to(home).parts) > 2 and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def make_parents(path: Path, home: Path, created: list[str]) -> None:
    missing = [parent for parent in reversed(path.parents) if parent.is_relative_to(home) and not os.path.lexists(parent)]
    for parent in missing:
        parent.mkdir()
        created.append(str(parent.relative_to(home)))


def add_tokens(path: Path, tokens: list[str]) -> None:
    """Add the tokens `permissions.deny` of an existing JSON config lacks; no file, no change."""
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        deny = data.setdefault("permissions", {}).setdefault("deny", [])
        if missing := [token for token in tokens if token not in deny]:
            deny.extend(missing)
            atomic_write(path, json.dumps(data, indent=2) + "\n")


def write(rel: str, kind: str, value: str, home: Path, ours: bool, roots: set[str], created: list[str]) -> str | None:
    """Write one entry; "" when it is in place, a line when the user's file or link keeps the path, else None."""
    path = home / rel
    if kind == "link" and path.is_symlink() and str(path.readlink()) == value:
        return ""
    if kind == "file" and path.is_file() and not path.is_symlink() and path.read_text(encoding="utf-8") == value:
        return ""
    if os.path.lexists(path):
        if not (ours or (path.is_symlink() and into(path, roots))):
            return f"  kept {tilde(path, home)}: yours, so el-capitan's is not installed there"
        if path.is_dir() and not path.is_symlink():
            return f"  kept {tilde(path, home)}: a directory where el-capitan writes a {kind}"
        path.unlink()
    make_parents(path, home, created)
    if kind == "link":
        path.symlink_to(value)
    else:
        atomic_write(path, value)
    return None


def retire_legacy(checkout: Path, home: Path, roots: set[str], manifest: dict) -> list[str]:
    """Remove what the layout before the adapters registered, so no harness loads a rule, agent or hook twice: the
    registrations before the scripts they run."""
    lines, gone = retire_cursor_hooks(checkout, home, manifest), 0
    for name in LEGACY_LINKS:
        directory = home / name
        links = [directory] if directory.is_symlink() else sorted(directory.iterdir()) if directory.is_dir() else []
        for link in links:
            agent_dir = name == ".cursor/agents" and link.name in adapters.AGENT_DIRS
            if link.is_symlink() and not agent_dir and into(link, roots):
                link.unlink()
                gone += 1
    # A skill or reference deleted from the checkout leaves a dangling link (and the folders it alone filled).
    for top, _, names in os.walk(home / ".cursor" / "skills"):
        for link in (Path(top) / name for name in names):
            if link.is_symlink() and not link.exists() and into(link, roots):
                remove(link, home)
                gone += 1
    for name in manifest.pop("rendered_agents", []):
        path = home / name
        if path.is_file() and not path.is_symlink():
            path.unlink()
            gone += 1
    manifest.pop("rendered_from", None)
    for name in ("agents", "skills"):
        link = home / ".claude" / name
        if link.is_symlink() and os.path.realpath(link) == os.path.realpath(home / ".cursor" / name):
            link.unlink()
            gone += 1
    if gone:
        lines.append(f"  retired {gone} link(s) and copies of the layout before the adapters (~/.cursor/rules, ~/.cursor/agents, ~/.claude/hooks)")
    return lines


def retire_cursor_hooks(checkout: Path, home: Path, manifest: dict) -> list[str]:
    """el-capitan's entries in ~/.cursor/hooks.json, by the settings merger's own match (`hooks_retirement.retired`); the
    file goes when install created it and nothing else is left. A file that is not JSON is left as it is, with a line."""
    hooks = home / ".cursor" / "hooks.json"
    spec = importlib.util.spec_from_file_location("hooks_retirement", checkout / ".claude" / "hooks_retirement.py")
    if not hooks.is_file() or spec is None or spec.loader is None:
        return []
    try:
        data = json.loads(hooks.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"  WARNING: ~/.cursor/hooks.json is not readable JSON ({error}); its el-capitan entries are left: remove them by hand"]
    retirement = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(retirement)
    lines: list[str] = []
    recorded = manifest.pop("cursor_hooks", None) or {}
    if isinstance(data, dict) and isinstance(data.get("hooks"), dict):
        before = json.dumps(data)
        for event, items in list(data["hooks"].items()):
            ours = [item for item in items if isinstance(item, dict) and retirement.retired(item.get("command"))] if isinstance(items, list) else []
            kept = [item for item in items if item not in ours] if isinstance(items, list) else items
            if kept:
                data["hooks"][event] = kept
            else:
                del data["hooks"][event]
        if json.dumps(data) != before:
            if not data["hooks"] and recorded.get("created"):
                hooks.unlink()
            else:
                atomic_write(hooks, json.dumps(data, indent=2) + "\n")
            lines.append("  removed el-capitan's registrations from ~/.cursor/hooks.json (the plugin registers them)")
    return lines


def apply(checkout: Path, home: Path, dry_run: bool = False) -> list[str]:
    manifest = load(home)
    roots, recorded = roots_of(checkout, manifest), set(manifest.get("rendered", []))
    wanted = entries(checkout, home)
    if dry_run:
        return [f"  [dry-run] install {len(wanted)} rendered entries for {', '.join(adapters.IDS)}"]
    lines = retire_legacy(checkout, home, roots, manifest)
    for rel in sorted(recorded - set(wanted)):
        path = home / rel
        if path.is_symlink() or path.is_file():
            remove(path, home)
            lines.append(f"  removed {tilde(path, home)}: no adapter renders it any more")
    written, created = [], []
    for rel, (kind, value) in sorted(wanted.items()):
        if kind == "deny":
            add_tokens(home / rel, json.loads(value))
        elif kind in ("link", "file"):
            line = write(rel, kind, value, home, rel in recorded, roots, created)
            if line:
                lines.append(line)
            else:
                written.append(rel)
    manifest["rendered"] = written
    manifest["dirs"] = list(dict.fromkeys([*manifest.get("dirs", []), *created]))
    save(home, manifest)
    lines.append(f"  installed {len(written)} rendered entries for {', '.join(adapters.IDS)}")
    return lines


def refresh(home: Path) -> int:
    """Rewrite each recorded agent file that differs from its render from the installed checkout (a pull, a persona edit,
    a config change). The hook rules and registrations change only at install."""
    manifest = load(home)
    recorded, changed = set(manifest.get("rendered", [])), 0
    for rel, (kind, value) in entries(Path(manifest["venv"]["checkout"]), home).items():
        path = home / rel
        agent = "/agents/" in f"/{rel}" and rel.endswith(".md")
        if agent and kind == "file" and rel in recorded and path.is_file() and not path.is_symlink() and path.read_text(encoding="utf-8") != value:
            atomic_write(path, value)
            changed += 1
    return changed


def diff(checkout: Path, home: Path) -> list[str]:
    """Each rendered link or file the installed one does not match (the hook rules included), and each recorded entry
    no adapter renders."""
    problems: list[str] = []
    wanted = entries(checkout, home)
    for rel, (kind, value) in sorted(wanted.items()):
        path = home / rel
        if kind == "link" and not (path.is_symlink() and str(path.readlink()) == value):
            problems.append(f"~/{rel} is not a link to {value}")
        elif kind == "file" and not (path.is_file() and path.read_text(encoding="utf-8") == value):
            problems.append(f"~/{rel} differs from its render")
    stale = sorted(set(load(home).get("rendered", [])) - set(wanted))
    return problems + [f"~/{rel} is installed but no adapter renders it" for rel in stale]


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["show"] and len(argv) == 5:
            print(adapters.adapter(argv[1]).render(Path(argv[4]), Path(argv[3]))[argv[2]][1], end="")
            return 0
        if argv[:1] == ["refresh"] and len(argv) == 2:
            changed = refresh(Path(argv[1]))
            print(f"agents: re-rendered {changed} stale agent file(s)" if changed else "", end="\n" if changed else "")
            return 0
        if argv[:1] in (["apply"], ["diff"]) and len(argv) in (3, 4):
            home, checkout = Path(argv[1]), Path(argv[2])
            if argv[0] == "apply":
                print("\n".join(apply(checkout, home, argv[3:] == ["--dry-run"])))
            else:
                problems = diff(checkout, home)
                print("\n".join(problems), end="\n" if problems else "")
                return 1 if problems else 0
            return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"harness_install: {error}", file=sys.stderr)
        return 2
    print("usage: harness_install apply|diff <home> <checkout> [--dry-run] | refresh <home> | show <harness> <path> <home> <checkout>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
