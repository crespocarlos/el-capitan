"""The gh argv of one read (`view`, `repo`, `issue`, `diff`) and the argparse verb that asks for it.

`crew-pr-actions.py` runs and prints these reads (`review_pr_reads`); `crew-ls` asks `view` and `repo`
in process (`ls_data`). gh takes PR and issue numbers positionally and `--repo` as its scope flag.
"""

from __future__ import annotations

import argparse

ALIASES = {"branch": "headRefName"}
DEFAULT_FIELDS = {"view": "number,url,title,state,isDraft,headRefName,headRefOid,baseRefName", "repo": "nameWithOwner", "issue": "title,body"}


def field_list(value: str) -> list[str]:
    """`branch,title,files` as three names, so spaces and a trailing comma are harmless."""
    return [name.strip() for name in value.split(",") if name.strip()]


def gh_fields(fields: list[str]) -> list[str]:
    """The `--json` names for the fields asked for; `branch` is the one alias gh lacks."""
    return [ALIASES.get(name, name) for name in fields]


def flag(option: str, value: object) -> list[str]:
    """`[option, value]`, or nothing when the value is absent, so gh falls back to the checkout."""
    return [option, str(value)] if value not in (None, "") else []


def read_argv(command: str, args: argparse.Namespace) -> list[str]:
    """The exact `gh` argv for one read.

    gh takes the PR and issue numbers positionally and `--repo` as its scope flag, so the argv mirrors
    that rather than inventing options gh does not have. An absent `--repo` or number lets gh resolve
    the current checkout, which is how a prompt asks about its own branch.
    """
    repo = flag("--repo", args.repo)
    number = [str(args.pr)] if getattr(args, "pr", None) is not None else []
    if command == "diff":
        argv = ["pr", "diff", *number, *repo]
        return [*argv, "--name-only"] if args.name_only else argv
    fields = ",".join(gh_fields(args.field))
    if command == "repo":
        # `gh repo view` takes the repository positionally and has no `--repo` flag.
        return ["repo", "view", *([str(args.repo)] if args.repo else []), "--json", fields]
    if command == "issue":
        return ["issue", "view", str(args.number), *repo, "--json", fields]
    return ["pr", "view", *number, *repo, "--json", fields]


def add_read_parser(commands: argparse._SubParsersAction, name: str) -> argparse.ArgumentParser:
    """One read verb: `--repo` when the checkout is not the target, plus the fields it prints."""
    action = commands.add_parser(name)
    action.add_argument("--repo", help="OWNER/REPO; default the checkout's own repository")
    if name == "issue":
        action.add_argument("--number", required=True, type=int)
    else:
        action.add_argument("--pr", type=int, help="PR number; default the current branch's")
    if name == "diff":
        action.add_argument("--name-only", action="store_true", help="changed paths, one per line")
        return action
    action.add_argument("--json", action="store_true", help="the fetched record as JSON, not one bare line per field")
    action.add_argument("--field", type=field_list, default=field_list(DEFAULT_FIELDS[name]), help="comma-separated names; one bare line each, in this order")
    return action
