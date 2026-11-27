#!/usr/bin/env python3
"""Install health on one screen: links, hook registrations, managed blocks, auto-memory, tools and gh, state sizes.

Read only. Exit 0 healthy, 1 at least one problem (each `FAIL` line names its fix; a `WARN` is not one). The checks are
`doctor_checks.py`; the size limits are the `doctor` object of `~/.agent/config.json` (`task_gc.py`
holds the defaults, which apply, with a `FAIL config` line, when the file is invalid).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import maintenance_bootstrap  # noqa: F401

from doctor_checks import (
    ROOT,
    Line,
    check_auto_memory,
    check_blocks,
    check_hooks,
    check_links,
    check_state,
    check_tools,
)
from task_gc import DEFAULTS, ConfigError, Places, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crew-doctor.py", description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="skip `gh auth status`, the one network call")
    args = parser.parse_args(argv)
    home, places = Path.home(), Places.here()
    lines = []
    try:
        config = load_config(places.agent)
        limits = config["doctor"]
        lines.append(Line("ok", "config", f"crew ls scope (ls.repo): {config['ls']['repo']}"))
    except ConfigError as error:
        limits = dict(DEFAULTS["doctor"])
        lines.append(Line("FAIL", "config", f"{error}; fix the file (the default limits apply meanwhile)"))
    lines += [*check_links(home), *check_hooks(home), *check_blocks(home), *check_auto_memory(home),
              *check_tools(sign_in=not args.offline), *check_state(places, limits)]
    print(f"crew doctor: install from {ROOT}")
    for line in lines:
        print(f"  {line.level:<4}  {line.area:<6}  {line.text}")
    problems = sum(1 for line in lines if line.level == "FAIL")
    print("healthy" if not problems else f"{problems} problem(s): fix each FAIL line, then run crew doctor again")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
