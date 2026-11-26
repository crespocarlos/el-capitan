#!/usr/bin/env python3
"""Drive nightshift-pr-helper e2e runs through its local HTTP API; Kibana-specific by design.

Subcommands: `doctor` (read-only preflight), `worktrees`, `start`, `status`, `report`, `followup`,
`stop`, `stack-stop`; server `NIGHTSHIFT_URL` (default `http://localhost:3737`), PR keys
`owner__repo__number`. Never the queue or `post-comment` (both comment on the PR). Exit: 0 ok,
1 rejected (nightshift's `error` text), 2 invalid invocation, 3 server unreachable. Logic: `nightshift/`.
"""
from __future__ import annotations

import argparse
import sys

import review_bootstrap  # noqa: F401

# Re-exported for the contract tests, which exercise the probes without a live server, and so a
# caller reading this command keeps one import site after the split.
from nightshift.client import (
    ApiError,
    Unreachable,
    base_url,
)
from nightshift.commands import (
    followup,
    report,
    stack_stop,
    start,
    status,
    stop,
    worktrees,
)
from nightshift.doctor import doctor
from nightshift.location import (
    dev_stack_current,
    duplicate_config_keys,
    is_canonical_remote,
    port_in_use,
)

from lib.output import DEFAULT_MAX_CHARS

__all__ = [  # the public names: re-exported for callers and tests that import this command file
    "dev_stack_current",
    "duplicate_config_keys",
    "is_canonical_remote",
    "main",
    "port_in_use",
]

EXIT_UNREACHABLE = 3


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drive nightshift-pr-helper e2e runs over HTTP; PR keys are owner__repo__number.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="read-only preflight: repo, build, server, machine, agent CLI")
    worktree_parser = commands.add_parser("worktrees", help="list designated Kibana worktrees")
    worktree_parser.add_argument("--limit", type=int, default=None, help="show at most N worktrees")
    worktree_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                                 help=f"bound the JSON (default {DEFAULT_MAX_CHARS})")
    start_parser = commands.add_parser("start", help="start an e2e run (never queued, never comments)")
    start_parser.add_argument("key")
    start_parser.add_argument("--worktree", required=True)
    start_parser.add_argument("--deploy", action="store_true", help="deploy the PR into that worktree first")
    start_parser.add_argument("--instructions", default="", help="extra focus for the tester")
    for name, help_text in (("status", "run state"), ("report", "the finished report"),
                            ("stop", "stop the run")):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("key")
        if name == "status":
            sub.add_argument("--worktree-path", default="",
                             help="local path to the deployed worktree, to tail its log on failure")
    stack_parser = commands.add_parser("stack-stop", help="stop the Kibana/ES stack in a worktree")
    stack_parser.add_argument("--worktree", required=True)
    followup_parser = commands.add_parser("followup", help="ask the tester a follow-up question")
    followup_parser.add_argument("key")
    followup_parser.add_argument("text")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    if getattr(args, "max_chars", DEFAULT_MAX_CHARS) < 1:
        print("nightshift-e2e: --max-chars must be at least 1", file=sys.stderr)
        return 2
    handlers = {"doctor": doctor, "worktrees": worktrees, "start": start,
                "status": status, "report": report, "followup": followup, "stop": stop,
                "stack-stop": stack_stop}
    try:
        return handlers[args.command](args)
    except Unreachable as error:
        print(f"nightshift-e2e: {base_url()} unreachable: {error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    except ApiError as error:
        print(f"nightshift-e2e: {error}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"nightshift-e2e: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
