#!/usr/bin/env python3
"""Drive nightshift-pr-helper e2e runs through its local HTTP API.

Subcommands: `doctor` (read-only machine and server preflight), `worktrees`, `start`,
`status`, `report`, `followup`, `stop`, `stack-stop`. The server is `NIGHTSHIFT_URL`, default
`http://localhost:3737`; PR keys are nightshift's `owner__repo__number`.

Deliberately absent: the queue (`POST /api/e2e/queue`) and `post-comment`. A queued run
comments on the PR by default, which is external state the caller has to confirm, and a
direct start already reaches the same runner.

Exit codes: 0 ok, 1 request rejected or invalid output, 2 invalid invocation, 3 server
unreachable. Diagnostics for 1 come from nightshift's own `error` field, so its message
for an untracked PR or a disabled e2e reaches the user unchanged.

This file is the argparse entry point only: the HTTP client, the checkout and machine probes, the
preflight assembly, and the run operations live in the `nightshift/` package beside it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REVIEW_DIR = Path(__file__).resolve().parent
_TOOLS_ROOT = _REVIEW_DIR.parent
for _path in (_TOOLS_ROOT, _REVIEW_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from lib.output import DEFAULT_MAX_CHARS  # noqa: E402
from nightshift.client import Unreachable, ApiError, base_url  # noqa: E402
from nightshift.commands import (  # noqa: E402
    followup,
    is_end_to_end as _is_end_to_end,
    report,
    stack_stop,
    start,
    status,
    stop,
    tail_fatal,
    worktrees,
)
from nightshift.doctor import doctor  # noqa: E402

# Re-exported for the contract tests, which exercise the probes without a live server, and so a
# caller reading this command keeps one import site after the split.
from nightshift.checks import config_checks, location_checks, machine_notes, server_checks  # noqa: E402,F401
from nightshift.checks import agent_check  # noqa: E402,F401
from nightshift.client import check_key  # noqa: E402,F401
from nightshift.location import (  # noqa: E402,F401
    build_is_fresh,
    dev_stack_current,
    duplicate_config_keys,
    elastic_remote,
    is_canonical_remote,
    launchd_state,
    plist_working_directory,
    port_in_use,
    ports_status,
    resolve_root,
)

UNREACHABLE = 3


def build_parser() -> argparse.ArgumentParser:
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
    args = build_parser().parse_args()
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
        return UNREACHABLE
    except ApiError as error:
        print(f"nightshift-e2e: {error}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"nightshift-e2e: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
