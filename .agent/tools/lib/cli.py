"""Command-line helpers: one parser factory for the shared `--help` and exit-2 contract.

`build_parser` returns the parser every tool would otherwise construct by hand, so the description
and formatter choices stay uniform. `fail` prints a message to stderr and returns its exit code,
which is 2 for unusable infrastructure or invalid invocation.
"""
from __future__ import annotations

import argparse
import sys

EXIT_INVALID = 2


def build_parser(
    description: str, *, raw_description: bool = False, epilog: str | None = None
) -> argparse.ArgumentParser:
    """A parser whose `--help` is the tool's docstring, optionally with a verbatim description."""
    formatter = argparse.RawDescriptionHelpFormatter if raw_description else argparse.HelpFormatter
    return argparse.ArgumentParser(description=description, epilog=epilog, formatter_class=formatter)


def fail(message: str, code: int = EXIT_INVALID) -> int:
    """Print `message` to stderr and return `code`, for a `return fail(...)` error path."""
    print(message, file=sys.stderr)
    return code
