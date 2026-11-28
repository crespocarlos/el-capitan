"""The agent tools, one verb each: `crew-tool.py <verb> [--json] [--field NAME]`.

Each verb is a typed core function (`VERBS`) whose signature builds its command line: no default is positional, a
`bool` a switch, a `list` several values, a `Literal` its choices; the docstring's `Args:` lines are the help. Every
verb answers in one envelope (`envelope.py`); `--field` prints one data field bare (exit 1 when it is unavailable).
Exits: 0, 1 a refusal or failure, 2 a bad invocation or missing infrastructure, 3 a duplicate memory unit.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import types
import typing

from crew.lib.errors import ToolError
from crew.tools.envelope import Parser, failed, ok, text

VERBS = {
    "task-context": "crew.core.task.api:task_context",
    "task-list": "crew.core.task.api:task_list",
    "repo-facts": "crew.core.task.api:repo_facts",
    "guidance": "crew.core.task.api:guidance",
    "pr-read": "crew.core.review.review_pr_reads:pr_read",
    "mem-recall": "crew.core.memory.memory_search:mem_recall",
    "review-prepare": "crew.core.review.review_prepare:review_prepare",
    "task-transition": "crew.core.task.api:task_transition",
    "task-log": "crew.core.task.api:task_log",
    "task-prepare": "crew.core.task.api:task_prepare",
    "task-lock": "crew.core.task.api:task_lock",
    "task-ship": "crew.core.task.api:task_ship",
    "review-dispatch": "crew.core.review.assemble_build:review_dispatch",
    "review-finish": "crew.core.review.review_consolidate:review_finish",
    "review-record-outcome": "crew.core.review.review_report:review_record_outcome",
    "mem-write": "crew.core.memory.memory_add:mem_write",
}
ARG = re.compile(r"^\s+(\w+): (.+)$", re.M)
REQUIRED = object()  # a parameter with no default: positional


def function(verb: str) -> typing.Callable[..., object]:
    module, name = VERBS[verb].split(":")
    return getattr(importlib.import_module(module), name)


def parameters(verb: typing.Callable[..., object]) -> dict[str, object]:
    """Each parameter's default, `REQUIRED` for none (read from the code object: `inspect` costs 5 ms a call)."""
    code, defaults = verb.__code__, verb.__defaults__ or ()
    names = code.co_varnames[: code.co_argcount]
    return {name: (defaults[i - len(names) + len(defaults)] if i >= len(names) - len(defaults) else REQUIRED) for i, name in enumerate(names)}


def add_arguments(parser: Parser, verb: typing.Callable[..., object]) -> None:
    """One argument per parameter, from its annotation and default; `field` is the common `--field`."""
    hints, doc = typing.get_type_hints(verb), verb.__doc__ or ""
    helps = dict(ARG.findall(doc.partition("Args:")[2]))
    for name, default in parameters(verb).items():
        if name == "field":
            continue
        kind = hints[name]
        if typing.get_origin(kind) in (typing.Union, types.UnionType):  # `X | None`: X
            kind = next(part for part in typing.get_args(kind) if part is not type(None))
        options: dict = {"help": helps.get(name)}
        if typing.get_origin(kind) is typing.Literal:
            options["choices"] = [choice for choice in typing.get_args(kind) if choice]
        elif kind is bool:
            options["action"] = "store_true"
        elif typing.get_origin(kind) is list:
            options["nargs"] = "*" if default is not REQUIRED else "+"
        else:
            options["type"] = kind
        if default is REQUIRED:
            parser.add_argument(name, **options)
        else:
            parser.add_argument(f"--{name.replace('_', '-')}", dest=name, default=default, **options)


def make_parser(only: str = "") -> Parser:
    common = Parser(add_help=False)
    common.add_argument("--json", action="store_true", help="the envelope as compact JSON")
    common.add_argument("--field", default="", help="print this one data field bare, for a shell assignment")
    parser = Parser(prog="crew-tool.py", description=f"The agent tools, one verb each, in one envelope. VERB is one of: {', '.join(VERBS)}.")
    verbs = parser.add_subparsers(dest="verb", required=True, parser_class=Parser, metavar="VERB", help="`crew-tool.py VERB --help` describes it")
    for name in [only] if only else VERBS:
        verb = function(name)
        summary = (verb.__doc__ or "").strip().splitlines()[0]
        add_arguments(verbs.add_parser(name, description=summary, parents=[common]), verb)
    return parser


def field_text(value: object) -> str:
    return "\n".join(map(str, value)) if isinstance(value, list) else value if isinstance(value, str) else json.dumps(value)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    args = make_parser(arguments[0] if arguments and arguments[0] in VERBS else "").parse_args(arguments)
    verb, given = function(args.verb), vars(args)
    wanted = {name: given[name] for name in parameters(verb)}
    code = 0
    try:
        envelope = ok(verb(**wanted), [])
        data = envelope["data"]
        if args.field and (not isinstance(data, dict) or data.get(args.field) is None):
            raise ToolError("unavailable", f"{args.field} is unavailable here", args.verb)
    except ToolError as error:
        envelope, code = failed(error, []), error.exit
    if args.json:
        print(json.dumps(envelope, separators=(",", ":")))
    elif not envelope["ok"]:
        print(text(envelope), file=sys.stderr)
    elif args.field:
        print(field_text(envelope["data"][args.field]))
    else:
        print(text(envelope))
    return code


if __name__ == "__main__":
    sys.exit(main())
