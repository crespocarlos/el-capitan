#!/usr/bin/env python3
"""Harness-neutral Markdown memory CLI backed by a rebuildable SQLite FTS5 index.

This file is the argparse entry point only: the logic lives in the sibling `memory_*.py` modules
(store, units, context, search, journal, maintenance), found through `memory_bootstrap`.
"""
import argparse
import sqlite3
import sys

import memory_bootstrap  # noqa: F401

from memory_add import add, cite, listing, show, supersede
from memory_frontmatter import STATUSES, TYPES
from memory_inbox import import_inbox
from memory_journal import journal_add, journal_import
from memory_maintenance import consolidate, init_store
from memory_paths import MemoryStoreError
from memory_search import context, search

from lib.output import DEFAULT_MAX_CHARS


def add_unit_parsers(commands) -> None:
    """`add`: one unit written from stdin, with its type, scope, title, and metadata."""
    add_parser = commands.add_parser("add", help="write one unit from stdin")
    add_parser.add_argument("--type", required=True, choices=sorted(TYPES))
    add_parser.add_argument("--scope", required=True)
    add_parser.add_argument("--title", required=True)
    add_parser.add_argument("--keywords", nargs="*", default=[])
    add_parser.add_argument("--paths", nargs="*", default=[])
    add_parser.add_argument("--evidence", nargs="*", default=[])
    add_parser.add_argument("--force", action="store_true")


def add_read_parsers(commands) -> None:
    """`search`, `context`, and `show`: the read paths over the index."""
    search_parser = commands.add_parser("search", help="full-text search; --json for machines")
    search_parser.add_argument("query")
    search_parser.add_argument("--repo", help="repository scope; '*' searches every scope")
    search_parser.add_argument("--type", choices=sorted(TYPES))
    search_parser.add_argument("--include-observations", action="store_true")
    search_parser.add_argument("--top", type=int, default=5)
    search_parser.add_argument("--json", action="store_true")
    search_parser.add_argument("--limit", type=int, default=None, help="print at most N results")
    search_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                               help="truncate output past N chars, with a marker")
    context_parser = commands.add_parser("context", help="ranked recall for a plan or review")
    context_parser.add_argument("--repo")
    context_parser.add_argument("--query", default="")
    context_parser.add_argument("--paths", nargs="*", default=[])
    context_parser.add_argument("--mode", choices=["session", "plan", "implement", "review", "debug"], default="plan")
    context_parser.add_argument("--include-observations", action="store_true")
    context_parser.add_argument("--json", action="store_true")
    context_parser.add_argument("--limit", type=int, default=None, help="print at most N results")
    context_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                                help="truncate output past N chars, with a marker")
    context_parser.add_argument("--warn-unavailable", action="store_true",
                                help="an unavailable store prints `none` and a stderr warning, exit 0")
    show_parser = commands.add_parser("show", help="print one unit")
    show_parser.add_argument("id")
    show_parser.add_argument("--scope", default=None,
                             help="look in this scope instead of the current repo, then global")


def add_write_parsers(commands) -> None:
    """The unit mutations that are not `add`: list, supersede, and cite."""
    list_parser = commands.add_parser("list", help="list units; --json for machines")
    list_parser.add_argument("--scope")
    list_parser.add_argument("--status", choices=sorted(STATUSES))
    list_parser.add_argument("--json", action="store_true")
    list_parser.add_argument("--limit", type=int, default=None, help="print at most N units")
    list_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                             help="truncate output past N chars, with a marker")
    supersede_parser = commands.add_parser("supersede")
    supersede_parser.add_argument("old")
    supersede_parser.add_argument("new")
    cite_parser = commands.add_parser("cite")
    cite_parser.add_argument("ids", nargs="+")
    cite_parser.add_argument("--outcome", required=True, choices=["used", "helped", "misled"])


def add_maintenance_parsers(commands) -> None:
    """Bulk operations: consolidate and import-inbox."""
    consolidate_parser = commands.add_parser("consolidate")
    consolidate_parser.add_argument("--dry-run", action="store_true")
    inbox_parser = commands.add_parser("import-inbox")
    inbox_parser.add_argument("--all", action="store_true",
                              help="take every draft; a bare call refuses, because the inbox may "
                                   "hold drafts from earlier sessions")
    inbox_parser.add_argument("files", nargs="*")


def add_journal_parsers(commands) -> None:
    """The journal subcommands: `add` for one entry, `import` for a whole directory."""
    journal_parser = commands.add_parser("journal")
    journal_commands = journal_parser.add_subparsers(dest="journal_command", required=True)
    journal_add_parser = journal_commands.add_parser("add")
    journal_add_parser.add_argument("--title", required=True)
    journal_add_parser.add_argument("--tags", nargs="*", default=[])
    journal_add_parser.add_argument("--repo")
    journal_add_parser.add_argument("--date")
    journal_import_parser = journal_commands.add_parser("import")
    journal_import_parser.add_argument("--dry-run", action="store_true")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Typed, repo-scoped memory: units, search, journal.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create the store and index")
    add_unit_parsers(commands)
    add_read_parsers(commands)
    add_write_parsers(commands)
    add_maintenance_parsers(commands)
    add_journal_parsers(commands)
    return parser


def unavailable(args: argparse.Namespace, message: str) -> int:
    """Exit 2 with the message; `context --warn-unavailable` prints `none` and a warning and exits 0."""
    if getattr(args, "warn_unavailable", False):
        print(f"warning: memory unavailable — {message.splitlines()[0]}", file=sys.stderr)
        print("none")
        return 0
    print(message, file=sys.stderr)
    return 2


def main() -> int:
    args = make_parser().parse_args()
    handlers = {
        "init": lambda _: init_store(), "add": add, "search": search, "context": context,
        "show": show, "list": listing, "supersede": supersede, "cite": cite,
        "import-inbox": import_inbox, "consolidate": consolidate,
    }
    try:
        if args.command == "journal":
            return journal_add(args) if args.journal_command == "add" else journal_import(args)
        return handlers[args.command](args)
    except MemoryStoreError as error:
        return unavailable(args, str(error))
    except PermissionError as error:
        return unavailable(args, f"memory store not writable: {error}\n"
                           "hint: a sandbox likely blocks writes outside the workspace; "
                           "retry this command unsandboxed (or set CREW_MEMORY_DIR to a writable path)")
    except (OSError, sqlite3.Error) as error:
        return unavailable(args, f"memory store unavailable: {error}")


if __name__ == "__main__":
    sys.exit(main())
