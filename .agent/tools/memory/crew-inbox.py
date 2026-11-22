#!/usr/bin/env python3
"""What needs a human decision, in one place.

The inbox drafts exist because a model wrote them; they stay because nobody was asked. Two flows
produced that silence: a subagent cannot ask a question (its turn ends into a parent that is already
finished), and a turn that asked once was never asked again. This command is the read side both
needed — a list a session can print at start and a person can run when they wonder what is pending.

It reports only; importing stays an explicit, named decision because bare `import-inbox` takes drafts
left by earlier sessions too.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from memory_frontmatter import parse_unit  # noqa: E402
from memory_paths import memory_root  # noqa: E402


def drafts(root: Path) -> list[dict]:
    """Every inbox draft, newest first, with the fields a decision needs."""
    found = []
    for path in sorted((root / ".inbox").glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            unit = parse_unit(path, inferred_scope="global")
        except (OSError, ValueError):
            found.append({"file": path.name, "type": "invalid", "title": "", "scope": ""})
            continue
        found.append({"file": path.name, "type": unit.get("type", ""),
                      "title": unit.get("title", ""), "scope": unit.get("scope", ""),
                      "modified": path.stat().st_mtime})
    return found


def queued(root: Path) -> list[dict]:
    """Stop-hook entries that asked for a review, so a session knows one is outstanding.

    The queue is a log of asks, not a to-do list: an ask is satisfied when the drafts it produced
    exist, and nothing else can tell. Rather than pretending to track completion, this reports the
    count and lets `--drain` clear it once a person has decided. An append-only file that never
    drains would report outstanding work forever.
    """
    path = root / ".sessions" / "review-queue.jsonl"
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def drain(root: Path) -> int:
    """Clear the ask log after the drafts have been decided. The drafts themselves stay untouched."""
    path = root / ".sessions" / "review-queue.jsonl"
    if path.is_file():
        path.unlink()
    print("review queue: cleared (drafts are unaffected)")
    return 0


def report(root: Path, as_json: bool) -> int:
    """Print what is pending. Exit 0 whether or not anything is, because empty is a valid answer."""
    pending = drafts(root)
    entries = queued(root)
    if as_json:
        print(json.dumps({"drafts": pending, "queued_reviews": entries}, indent=2))
        return 0
    if not pending and not entries:
        print("inbox: empty")
        return 0
    print(f"inbox: {len(pending)} draft(s) awaiting a decision")
    for item in pending:
        print(f"  {item['type']:<14} {item['file']}")
        if item["title"]:
            print(f"  {'':14} {item['title']}")
    if entries:
        print(f"queued reviews: {len(entries)} session(s) asked for capture")
    print()
    print("import by name, never bare: crew-mem.py import-inbox <file> …")
    print("bare import-inbox takes every draft, including earlier sessions'.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="List drafts and queued reviews awaiting a decision.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--drain", action="store_true",
                        help="clear the ask log once every draft has been decided")
    args = parser.parse_args()
    root = args.root or memory_root()
    if args.drain:
        return drain(root)
    return report(root, args.json)


if __name__ == "__main__":
    sys.exit(main())
