#!/usr/bin/env python3
"""Install health on one screen: links, hooks, blocks, auto-memory, rendered agents, tools and gh, state, MCP servers.

Read only. Exit 0 healthy, 1 at least one problem (each `FAIL` line names its fix; a `WARN` is not one).
The checks are `doctor_checks.py` and `doctor_mcp.py`; the size limits and MCP server names are the `doctor`
and `mcp` objects of `~/.agent/config.json` (`task_gc.py` holds the defaults, which apply, with a
`FAIL config` line, when the file is invalid).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from crew.maintenance.doctor_checks import ROOT, Line, check_auto_memory, check_blocks, check_cursor_duplicates, check_hooks, check_links
from crew.maintenance.doctor_env import check_environment, check_state, check_tools
from crew.maintenance.doctor_mcp import check_mcp, check_rendered_agents
from crew.task.task_gc import DEFAULTS, ConfigError, Places, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crew-doctor.py", description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="skip `gh auth status`, the one network call")
    args = parser.parse_args(argv)
    home, places = Path.home(), Places.here()
    lines = []
    mcp: dict | None
    try:
        config = load_config(places.agent)
        limits, mcp = config["doctor"], config["mcp"]
        lines.append(Line("ok", "config", f"crew ls scope (ls.repo): {config['ls']['repo']}"))
    except ConfigError as error:
        limits, mcp = dict(DEFAULTS["doctor"]), None
        lines.append(Line("FAIL", "config", f"{error}; fix the file (the default limits apply meanwhile)"))
    lines += [
        *check_links(home),
        *check_hooks(home),
        *check_cursor_duplicates(home, Path.cwd()),
        *check_blocks(home),
        *check_auto_memory(home),
        *check_rendered_agents(home),
        *check_environment(home),
        *check_tools(sign_in=not args.offline),
        *check_state(places, limits),
        *check_mcp(home, mcp, Path.cwd(), dict(os.environ)),
    ]
    print(f"crew doctor: install from {ROOT}")
    for line in lines:
        print(f"  {line.level:<4}  {line.area:<6}  {line.text}")
    problems = sum(1 for line in lines if line.level == "FAIL")
    print("healthy" if not problems else f"{problems} problem(s): fix each FAIL line, then run crew doctor again")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
