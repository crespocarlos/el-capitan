#!/usr/bin/env python3
"""Print the next step a completed stage hands to, from the shared `next-steps.json` table.

The table answers which command runs after a stage (`lib/next_steps`). Exit: 0 with the answer on
stdout, 1 when the table has no rule for the key, 2 when the table cannot be read.
"""
from __future__ import annotations

import argparse
import json
import sys

import task_bootstrap  # noqa: F401

from lib.next_steps import known_stages, load_table, resolve, sentence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("key", nargs="?", help="<workflow>.<stage>.<outcome>, or <stage>.<outcome>")
    parser.add_argument("--json", action="store_true", help="print the rule as JSON")
    parser.add_argument("--why", action="store_true", help="print the rule's reason")
    parser.add_argument("--stages", action="store_true", help="list every stage the table answers")
    args = parser.parse_args(argv)
    try:
        rules = load_table()
    except ValueError as error:
        print(f"crew-next: {error}", file=sys.stderr)
        return 2
    if args.stages:
        print("\n".join(known_stages(rules)))
        return 0
    if not args.key:
        parser.error("a key is required unless --stages is passed")
    try:
        rule = resolve(rules, args.key)
    except ValueError as error:
        print(f"crew-next: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rule, sort_keys=True))
    elif args.why:
        print(rule["why"])
    else:
        print(sentence(rule))
    return 0


if __name__ == "__main__":
    sys.exit(main())
